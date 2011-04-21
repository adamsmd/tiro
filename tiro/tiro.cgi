#! /usr/bin/perl -T
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout
umask 0077; # Default to private files
delete @ENV{qw(PATH IFS CDPATH ENV BASH_ENV)}; # Make %ENV safer

# Configuration
use constant CONFIG_FILE => 'system/config.cfg';
use lib 'system/lib';

# Modules from Core
use CGI qw(-private_tempfiles -nosticky);
use CGI::Carp qw(carpout set_progname);
use Carp qw(verbose);
use Class::Struct;
use File::Copy qw(copy move); # NOTE: move() has tainting issues
use File::Path qw(mkpath);
use File::Spec::Functions;
use Time::HiRes qw(time);
sub say { print @_, "\n"; } # Emulate Perl 6 feature

# Modules not from Core
use Tiro::Config;
use Date::Manip;
use File::Slurp qw/slurp/; # Perl 6 feature
use List::MoreUtils qw/:all/;

################
# Structs
################

struct Submission=>{assignment=>'AssignmentConfig', user=>'UserConfig',
                    group=>'@', date=>'$', files=>'@', failed=>'$', late=>'$'};
struct File=>{name=>'$', size=>'$'};

struct UploadFile=>{name=>'$', handle=>'$'};

################
# Bootstrap
################

my $start_time = time();

set_progname("tiro.cgi (PID:$$ USER:$ENV{'REMOTE_USER'})"); # Warning Prefix

my $config = parse_global_config_file(CONFIG_FILE);

if ($config->log_file ne "") {
  open(my $LOG_FILE, ">>" . UnixDate("now", $config->log_file)) or
    die "Can't open log file ", $config->log_file, ": $!\n";
  carpout($LOG_FILE);
}

warn "+++ Starting tiro.cgi +++";
END { warn "--- Stopping tiro.cgi ---"; }

$CGI::POST_MAX = $config->max_post_size;
$ENV{PATH} = $config->path;
my $q = CGI->new;
panic("Connection limit (@{[$config->max_post_size]} bytes) exceeded.",
      "Submitted file too large?")
  if ($q->cgi_error() || "") =~ /^413/; # 413 POST too large
panic($q->cgi_error()) if $q->cgi_error();

exists $ENV{$_} and warn("$_: ", $ENV{$_}) for
  ("REMOTE_HOST", "REMOTE_USER", "HTTP_REFERER", "HTTP_X_FORWARDED_FOR");
warn "PARAM $_: ", join(":",$q->param($_)) for $q->param();

my %real_all_users = parse_user_configs($config);

################
# Input Parsing
################

# Input formats
sub date { ((UnixDate($_[0], "%O") or "") =~ m[^([A-Za-z0-9:-]+)$])[0]; }
sub file { (($_[0] or "") =~ m[^(?:.*[\\/])?([A-Za-z0-9_\. -]+)$])[0]; }
sub keyword { (($_[0] or "") =~ m[^([A-Za-z0-9_\.-]*)$])[0]; }
sub bool { $_[0] ? 1 : 0; }

# Basic Inputs
my $now = date "now";
define_param(
  do_download => \&bool, do_submit => \&bool,
  show_search_form => \&bool, show_submit_form => \&bool,
  show_results => \&bool, show_failed => \&bool, show_group => \&bool,
  start_date => \&date, end_date => \&date, only_latest => \&bool,
  reports => \&bool, guards => \&bool, submitted => \&keyword,
  sort_by => \&keyword, user_override => \&keyword);
use constant {
  SUBMITTED_YES=>"sub_yes", SUBMITTED_NO=>"sub_no", SUBMITTED_ANY=>"sub_any",
  SORT_ASSIGNMENT=>'sort_assignment', SORT_USER=>'sort_user',
  SORT_DATE=>'sort_date', SORT_FULL_NAME=>'sort_full_name'};

# Login
my ($tainted_user) = $config->user_override || $q->remote_user() =~ /^(\w+)\@/;

my $login = my $real_login = $real_all_users{$tainted_user};
panic("No such user: $tainted_user.", "Missing HTTPS?") unless defined $login;

if ($login->is_admin && user_override() ne "") {
  $login = $real_all_users{user_override()};
  panic("No such user for override: " . user_override()) unless $login;
}

my @all_users = $login->is_admin ?
  sort {$a->id cmp $b->id} values %real_all_users : ($login);
my @all_assignments = $login->is_admin ?
  list_assignments() : grep { $_->hidden_until le $now } list_assignments();

# Other inputs
use constant {USERS => "users", ASSIGNMENTS => "assignments", FILE => 'file' };
my @users = select_by_id([values %real_all_users], $q->param(USERS));

my @assignments = select_by_id(
  \@all_assignments, map { file $_ } $q->param(ASSIGNMENTS));

my $download = file $q->param(FILE);
my @upload_files =
  map {UploadFile->new(name=>file($_), handle=>$_)} ($q->upload(FILE));

$ENV{'TZ'} = Date_TimeZone(); # make reports see the timezone
sub same_group {
  my ($assignment, $user1, $user2) = @_;
  (grep {$user2->id eq $_->id} @{$assignment->groups->{$user1->id}}) ? 1 : 0;
}

################
# Main Code
################

error('Invalid file names (only "A-Za-z0-9_. -" characters allowed): ',
      join(", ", $q->param(FILE)))
  unless not any { not defined $_->name } @upload_files;
{ my @x = map { $_->name } @upload_files;
  error('Duplicate file names: ', join(", ", @x)) unless @x == uniq @x; }

if (do_download()) { download(); }
elsif (do_submit()) { upload(); }
else { main_view(); }

sub download {
  @assignments or error("No valid assignment for download");
  @users and ($login->is_admin or same_group($assignments[0], $users[0], $login)) or
    error("No valid user for download");
  start_date() or error("No valid date for download");
  defined $download or error("No valid file for download");
  my ($assignment, $user) = ($assignments[0]->id, $users[0]->id);
  my $path = filename($assignment, $user, start_date() .
                      (show_failed() ? ".tmp" : ""), $download);
  -f $path and -r $path or
    error("Can't get $download in $assignment for $user at @{[start_date()]}");
  print $q->header(-type=>'application/octet-stream',
                   -attachment=>$download, -Content_length=>-s $path);
  copy($path, *STDOUT) or die "Failed to send download: ", $!;
}

sub upload {
  my $assignment = $assignments[0] or error("No assignment for submission.");

  my $date = "$now.tmp";
  my $target_dir = filename($assignment->id, $login->id, $date);
  warn "Starting upload of @{[$_->name]} in $target_dir" for @upload_files;
  mkpath($target_dir) or error("Can't mkdir in @{[$assignment->id]} for " .
                               $login->id . " at $now: $!");
  my $umask = umask 0377;
  for my $upload_file (@upload_files) {
    copy($upload_file->handle, catfile($target_dir, $upload_file->name)) or
      error("Can't save @{[$upload_file->name]} in @{[$assignment->id]} " .
            "for @{[$login->id]} at $now: $!");
  }
  umask $umask;
  chmod 0500, $target_dir; # lock down the submission directory
  warn "Upload done for $_ (@{[-s catfile($target_dir, $_)]} bytes)" .
    " in $target_dir" for dir_list($target_dir);
  my ($error, @msg) = (0);
  for my $test (@{$assignment->guards}) {
    set_env($assignment, $login, $date);
    warn "Running guard: $test";
    push @msg, `$test`;
    warn "Exit code: $?";
    $error ||= $?;
  }
  if ($error) { error("Submission failed:", @msg); }
  move($target_dir, filename($assignment->id, $login->id, $now)) or
    error("Can't move TODO: $!");
  print $q->redirect(
      -status=>303, # HTTP_SEE_OTHER
      -uri=>form_url(SHOW_RESULTS(), 1, REPORTS(), reports(),
                     ASSIGNMENTS, $assignment->id, USERS, $login->id,
                     START_DATE(), $now, END_DATE(), $now));
}

sub main_view {
  my @rows;
  for my $assignment (@assignments) {
    my @shown_users = @users ? @users : @all_users;
    warn "SHOWN:", map {$_->id} @shown_users;
    @shown_users = grep {same_group($assignment, $login, $_)} @shown_users
      unless $login->is_admin;
    for my $user (@shown_users) {
      warn "USER:", $user->id;
      my @dates = list_submissions(
        $assignment, show_group() ? @{$assignment->groups->{$user->id}} : ($user));
      @dates = grep {start_date() le $_->date} @dates if start_date();
      @dates = grep {end_date() ge $_->date} @dates if end_date();
      @dates = grep {not $_->failed} @dates if not show_failed();
      @dates = ($dates[$#dates]) if $#dates != -1 and only_latest();    

      warn $#dates;
      push @rows, Submission->new(
        assignment=>$assignment, user=>@{$assignment->groups->{$user->id}}[0], date=>'', late=>0,
        group=>$assignment->groups->{$user->id}, files=>[])
        if submitted() ne SUBMITTED_YES and not @dates;
      push @rows, @dates if submitted() ne SUBMITTED_NO;
    }
  }
  my %seen;
  @rows = grep { ! $seen{$_->assignment->id.'\x00'.$_->user->id.'\x00'.$_->date}++} @rows;
#  @rows = intersect(@rows, sub {$_->assignment, @rows);

  @rows = sort {(sort_by() eq SORT_USER and
                 join('\x00', map {$_->id} @{$a->group}) cmp
                 join('\x00', map {$_->id} @{$b->group}))
                  or (sort_by() eq SORT_DATE and $a->date cmp $b->date)
                  or (sort_by() eq SORT_FULL_NAME and
                      join('\x00', map {$_->full_name} @{$a->group}) cmp
                      join('\x00', map {$_->full_name} @{$b->group}))
                  or ($a->assignment->id cmp $b->assignment->id)
                  or (join('\x00', map {$_->id} @{$a->group}) cmp
                      join('\x00', map {$_->id} @{$b->group}))
                  or ($a->date cmp $b->date) } @rows;

  pre_body();

  if (show_submit_form()) {
    for my $a (@assignments) {
      say $q->start_div({-class=>'assignment'});
      say $q->h2($a->id . ": ", $a->title);
      say $q->h4("Due by ", pretty_date($a->due)) unless $a->due eq "";
      say $q->div(scalar(slurp(catfile($config->assignments_dir,
                                       $a->text_file))))
        unless $a->text_file eq "";
      say $q->div($a->text) unless $a->text eq "";

      if ($a->file_count ne "") {
        say $q->start_form(
          -method=>'POST', -enctype=>&CGI::MULTIPART, -action=>'#');
        say $q->hidden(-name=>USER_OVERRIDE(), -default=>user_override());
        say $q->hidden(-name=>ASSIGNMENTS, -value=>$a->id, -override=>1);
        say $q->hidden(-name=>REPORTS(), -value=>1, -override=>1);
        say $q->p("File $_:", $q->filefield(-name=>FILE, -override=>1))
          for (1..$a->file_count);
        say $q->p($q->submit(DO_SUBMIT(), "Submit"));
        say $q->end_form();
      }
      say $q->p(); # Add extra space before the final line
      say $q->end_div();
    }
  }

  if (show_results()) {
    say $q->start_table({-class=>'results'});
    say $q->thead($q->Tr($q->th(["#", "Title", "User"," Name",
                                 "Reports", "Files", "Bytes"])));
    if (not @rows) {
      say row(7, $q->center('No results to display.',
                            'Browse or search to select assignment.'));
    } else {
      my @cells = ();
      for my $r (@rows) {
        my @url = (ASSIGNMENTS, $r->assignment->id, USERS, $r->user->id,
                   START_DATE(), $r->date, END_DATE(), $r->date,
                   SHOW_FAILED(), $r->failed);
        my @file_rows = @{$r->files} ?
          map {[href(form_url(@url,DO_DOWNLOAD(),1,FILE,$_->name), $_->name),
                "<span class='bytes'>".$_->size."</span>"] } @{$r->files} : ["(No files)", ""];
        my $num_files = @file_rows;
        my @new_cells =
          ($r->assignment->id, $r->assignment->title,
           join("; ",map {$_->id.($_->is_admin?" (admin)":"")} @{$r->group}),
           join("; ",map {$_->full_name} @{$r->group}),
           ($r->date ?
            (href(form_url(@url, GUARDS(), 1, REPORTS(), 1, SHOW_RESULTS(), 1),
                  pretty_date($r->date) . ' [' . $r->user->id . ']') .
             ($r->late ? " (Late)" : "") .
             ($r->failed ? " - FAILED" : "")) :
            ("(Nothing submitted)")));
        my $i = firstidx {not $_->[0] or $_->[0] ne $_->[1]} pairwise {[$a, $b]} @cells, @new_cells;
 
        say "<tr><td colspan='$i' rowspan='$num_files'></td>" if $i;
        say "<td style='border-top:solid 1px black;' rowspan='$num_files'>$_</td>" for @new_cells[$i..$#new_cells];

        for my $j (0..$#file_rows) {
          say $j == 0 ? "<td style='border-top:solid 1px black;'>" : "<td>";
          say $file_rows[$j]->[0], "</td>";
          say $j == 0 ? "<td style='border-top:solid 1px black;'>" : "<td>";
          say $file_rows[$j]->[1], "</td></tr>";
          say "<tr>";
        }
        say "</tr>";
        @cells = @new_cells;

        if ($r->date and (reports() or guards())) {
          my @programs = ((guards() ? @{$r->assignment->guards} : ()),
                          (reports() ? @{$r->assignment->reports} : ()));
          say '<tr><td colspan=2></td>';
          say '<td colspan=6 style="background:rgb(95%,95%,95%);">';
          say 'Submission ', ($r->failed ? 'FAILED' : 'succeeded');
          say ' and is ', ($r->late ? 'LATE' : 'on time'), '.';
          say '</td></tr>';
          set_env($r->assignment, $r->user, $r->date);
          for my $program (@programs) {
            say "<tr><td></td><td colspan=7><div>";
            warn "Running guard or report: $program";
            system $program;
            warn "Exit code: $?";
            say "</div></td></tr>";
          }
        }
      }
    }
    say $q->end_table();
  }

  say $config->text if not show_submit_form() and not show_results();
  post_body();
}

################
# Rendering Functions
################

sub warn_at_line { my $x = (caller(1))[2]; warn @_, " at line $x.\n"; $x }

sub panic { # Prints error without navigation components
  my $line = warn_at_line(@_);
  print $q->header();
  say $q->start_html(-title=>"Error: " . $config->title);
  say $q->h1("Error: " . $config->title);
  say $q->p([@_, "(At line $line and time " . date("now") . ".)"]);
  exit 0;
}

sub error { # Prints error with navigation components
  my $line = warn_at_line(@_);
  pre_body();
  say $q->h1({-style=>"color:red;"}, ["Error: ", @_]);
  say $q->p("(At line $line and time $now.)");
  post_body();
}

sub pre_body {
  print $q->header();
  say $q->start_html(-title=>$config->title, -style=>{-verbatim=><<'EOT'});
  th { vertical-align:top; text-align:left; }
  td { vertical-align:top; }
  h2 { border-bottom:2px solid black; }
  .navbar { padding:0.3em; width:19em; float:left; border:solid black 1px; }
  .navbar table { width:100%; }
  .navbar td { vertical-align: baseline; }
  .navbar form td { vertical-align: top; }
  .navbar>h3:first-child { margin-top:0; } /* Stop spurious margin */
  .search { width:100%; }
  .search select { width:100%; }
  .search input[type="text"] { width:90%; }
  .results { width:100%;border-collapse: collapse; }
  .results>thead { border-bottom:2px solid black; }
  .results>tbody { border-bottom:1px solid black; }
  .results>.bytes { text-align:right; }
/*  .results>tbody>TR+TR>td+td { text-align:right; }*/
/*  .results>tbody>TR+TR>td+td[colspan] { text-align:left; }*/
  .assignment { width:100%;border-bottom:1px solid black;margin-bottom:1.3em; }
  .body { margin-left:21em; }
  .footer { clear:left; text-align:right; font-size: small; }
  .welcome { float:right; font-weight:bold; }
  .hidden_until { color:red; }
EOT

  my $user_id = $login->id;
  if ($real_login->is_admin) {
    $user_id = $q->popup_menu(
      USER_OVERRIDE(), [sort keys %real_all_users], $login->id);
    $user_id .= $q->submit(-value=>'Change user');
    for ($q->param) {
      $user_id .= "\n" . $q->hidden(-name=>$_, -default=>$q->param($_))
        if $_ ne FILE() and $_ ne USER_OVERRIDE();
    }
  }

  say $q->start_form(-action=>"?".$q->query_string, -method=>'GET');
  say $q->div({-class=>'welcome'},
              "Welcome $user_id<br>Current time is", pretty_date($now));
  say $q->end_form();

  say $q->h1($config->title);

  say $q->start_div({-class=>'navbar'});

  say $q->h3("Select Assignment");
  say $q->start_table();
  for my $a (@all_assignments) {
    my $num_done = @{$a->dates};
    my $num_users = keys %real_all_users;
    my $late = (late_after($a) ne "" and $now ge late_after($a) and
                not any {$_->date le late_after($a)} @{$a->dates});
    say row(1, href(form_url(SHOW_SUBMIT_FORM(), 1, SHOW_GROUP(), 1,
                             SHOW_RESULTS(), 1,
                             ASSIGNMENTS, $a->id), $a->id . ": ", $a->title),
            ($num_done ? "&nbsp;&#x2611;" : "&nbsp;&#x2610;") .
            ($login->is_admin ? $q->small("&nbsp;($num_done/$num_users)"):"") .
            ($late ? "&nbsp;Late" : ""));
    say row(2, $q->small("&ensp;Due ", pretty_date($a->due)))
      unless $a->due eq "";
    say row(2, $q->small({-class=>'hidden_until'},
                         "&ensp;Hidden until", pretty_date($a->hidden_until)))
      unless $a->hidden_until lt $now;
  }
  say row(1, "(No assignments yet)") unless @all_assignments;
  say $q->end_table();

  say $q->h3("... or", href(form_url(), "Start Over"));

  say $q->h3("... or", href(form_url(SHOW_SEARCH_FORM(), 1), "Search"));
  if (show_search_form()) {
    say $q->start_form(-action=>'#', -method=>'GET');
    say $q->hidden(-name=>USER_OVERRIDE(), -default=>user_override());
    say map {$q->hidden(-name=>$_, -default=>1)} (
      SHOW_SEARCH_FORM(), SHOW_RESULTS(), SHOW_GROUP());
    say $q->start_table({-class=>'search'});
    map { say row(1, @$_) } (
      ["User:", multilist(USERS, map {$_->id} @all_users)],
      ["Assignment:", multilist(ASSIGNMENTS, map {$_->id} @all_assignments)],
      ["Show:", join($q->br(), map {$q->checkbox($_->[0],$_->[1],'y',$_->[2])}
                     ([ONLY_LATEST(), only_latest(), 'Only Most Recent'],
                      [SHOW_SUBMIT_FORM(), show_submit_form(), 'Submit Form'],
                      [REPORTS(), reports(), 'Reports'],
                      [GUARDS(), guards(), 'Guards'],
                      [SHOW_FAILED(), show_failed(), 'Failed Submissions']))],
      ["", $q->submit(-value=>"Search")],
      ["","&nbsp;"],
      ["<b>Advanced</b>", ""],
      ["Start date:", $q->textfield(-name=>START_DATE(), -value=>'Any')],
      ["End date:", $q->textfield(-name=>END_DATE(), -value=>'Any')],
      ["Status:", radio(SUBMITTED(), 0,
                        [SUBMITTED_ANY, "Any"],
                        [SUBMITTED_YES, "Submitted"],
                        [SUBMITTED_NO, "Unsubmitted"])],
      ["Sort by:", radio(SORT_BY(), 0,
                         [SORT_ASSIGNMENT, "Assignment"],
                         [SORT_USER, "User"],
                         [SORT_FULL_NAME, "Full Name"],
                         [SORT_DATE, "Date"])],
      ["", $q->submit(-value=>"Search")]);
    say $q->end_table();
    say $q->end_form();
  }
  say $q->end_div();

  say $q->start_div({-class=>'body'});
}

sub post_body {
  say $q->end_div();

  say $q->p({-class=>'footer'}, "Completed in",
            sprintf("%0.3f", time() - $start_time), "seconds by",
            $q->a({-href=>'http://www.cs.indiana.edu/~adamsmd/projects/tiro/'},
                  "Tiro") . ".");
  say $q->end_html();
  exit 0;
}

################
# Misc Functions
################

sub set_env {
  my ($assignment, $user, $date) = @_;
  $ENV{'TIRO_CONFIG_FILE'} = CONFIG_FILE;
  $ENV{'TIRO_LOGIN_ID'} = $login->id;
  $ENV{'TIRO_LOGIN_IS_ADMIN'} = $login->is_admin;
  $ENV{'TIRO_REAL_LOGIN_ID'} = $real_login->id;
  $ENV{'TIRO_REAL_LOGIN_IS_ADMIN'} = $real_login->is_admin;

  $ENV{'TIRO_SUBMISSION_DIR'} = filename($assignment->id, $user->id, $date);
  $ENV{'TIRO_SUBMISSION_USER'} = $user->id;
  $ENV{'TIRO_SUBMISSION_DATE'} = $date;
  $ENV{'TIRO_ASSIGNMENT_FILE'} = catfile(
    $config->assignments_dir, $assignment->path);

  $ENV{'TIRO_ASSIGNMENT_ID'} = $assignment->id;
  $ENV{'TIRO_ASSIGNMENT_TITLE'} = $assignment->title;
  $ENV{'TIRO_ASSIGNMENT_LATE_AFTER'} = $assignment->late_after;
  $ENV{'TIRO_ASSIGNMENT_DUE'} = $assignment->due;
  $ENV{'TIRO_ASSIGNMENT_FILE_COUNT'} = $assignment->file_count;
}

sub late_after { $_[0]->late_after ne "" ? $_[0]->late_after : $_[0]->due; }

sub list_assignments {
  map { my $path = $_;
        my ($id) = $_ =~ $config->assignments_regex;
        if (not defined $id) { (); }
        else {
          my $assignment = parse_assignment_file(\%real_all_users,
            catfile($config->assignments_dir, $path));
          $assignment->id($id);
          $assignment->path($path);
          $assignment->dates([
            map { $_ ? $_ : () }
            map {
              firstval {not $_->failed}
              sort {$a->date cmp $b->date}
              list_submissions($assignment, @{$assignment->groups->{$_->id}})
            } @all_users]);
          $assignment;
        }
  } dir_list($config->assignments_dir);
}

sub list_submissions {
  my ($assignment, @users) = @_;

  sort {$a->date cmp $b->date or $a->user->id cmp $b->user->id}
  grep {-d filename($_->assignment->id, $_->user->id, $_->date.$_->failed)}
  map { my $user = $_;
        map { $_ =~ /^(.*?)((\.tmp)?)$/;
              Submission->new(
                assignment=>$assignment, user=>$user, date=>date($1),
                group=>$assignment->groups->{$user->id},
                failed=>$2, files=>[list_files($assignment, $user, $1.$2)],
                late=>($1 gt late_after($assignment)), failed=>$2 ne '');
        } dir_list($config->submissions_dir,$assignment->id,$user->id)
  } @users;
}

sub list_files {
  my ($assignment, $user, $date) = @_;
  my @names = dir_list($config->submissions_dir,
                       $assignment->id, $user->id, $date);
  map { File->new(name=>$_, size=>-s filename(
                    $assignment->id, $user->id, $date, $_)) } @names;
}

sub filename { catfile($config->submissions_dir, @_); }

################
# HTML Utils
################

sub define_param {
  my (%hash) = @_;
  for my $key (keys %hash) {
    no strict 'refs';
    my $val = $hash{$key}->($q->param($key));
    *$key = sub () { $val; };
    *{uc $key} = sub () { $key; };
  }
}

sub form_url {
  my %args = @_;
  $args{USER_OVERRIDE()} = user_override() if $real_login->id ne $login->id;
  return "?" . join "&", map {"$_=$args{$_}"} keys %args;
}

sub pretty_date { UnixDate($_[0], $config->date_format) }

sub href { my ($href, @rest) = @_; $q->a({-href=>$href}, @rest); }

sub multilist {
  $q->scrolling_list(-name=>$_[0], -multiple=>1, -size=>5,
                     -values=>[@_[1..$#_]], -default=>[@_[1..$#_]]);
}

sub radio {
  my ($name, $def, @rest) = @_;
  scalar($q->radio_group(-columns=>1, -name=>$name, -default=>$rest[$def][0],
                         -values=>[map { $_->[0] } @rest],
                         -labels=>{map { @$_ } @rest}));
}

sub row { $q->Tr($q->td({-colspan=>$_[0]}, [@_[1..$#_]])) }

sub multirow {
  my ($prefix, @rows) = @_;
  "<tr>" . $q->td({-rowspan=>scalar(@rows)}, $prefix) .
    join("</tr><tr>", (map { $q->td($_) } @rows)) . "</tr>";
}

################
# General Utils
################

sub select_by_id {
  my ($list1, @list2) = @_;
  my %a = map {($_,1)} @list2;
  sort {$a->id cmp $b->id} grep {$a{$_->id}} @{$list1}
}

sub dir_list {
  opendir(my $d, catdir(@_)) or return ();
  my @ds = readdir($d);
  closedir $d;
  return sort grep {!/^\./} @ds; # skip dot files
}
