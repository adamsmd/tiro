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
use Carp qw(verbose);
use CGI qw(-private_tempfiles -nosticky);
use CGI::Carp qw(carpout set_progname);
use Class::Struct;
use File::Copy qw(copy move); # NOTE: move() has tainting issues
use File::Path qw(mkpath);
use File::Spec::Functions;
use Time::HiRes qw(time);
sub say { print @_, "\n"; } # Emulate Perl 6 feature

# Modules not from Core
use Tiro;
use Date::Manip;
use File::Slurp qw/slurp/; # Perl 6 feature
use List::MoreUtils qw/:all/;

struct UploadFile=>{name=>'$', handle=>'$'};

################
# Bootstrap
################

my $start_time = time();

set_progname("tiro.cgi (PID:$$ USER:$ENV{'REMOTE_USER'})"); # Warning Prefix

my $config = Tiro->new(CONFIG_FILE);

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

################
# Input Parsing
################

# Input formats
sub file { (($_[0] or "") =~ m[^(?:.*[\\/])?([A-Za-z0-9_\. -]+)$])[0]; }
sub keyword { (($_[0] or "") =~ m[^([A-Za-z0-9_\.-]*)$])[0]; }
sub bool { $_[0] ? 1 : 0; }

# Basic Inputs
my $now = tiro_date "now";
define_param(
  do_download => \&bool, do_submit => \&bool,
  show_search_form => \&bool, show_submit_form => \&bool,
  show_results => \&bool, show_failed => \&bool, show_group => \&bool,
  start_date => \&tiro_date, end_date => \&tiro_date, only_latest => \&bool,
  reports => \&bool, guards => \&bool, submitted => \&keyword,
  sort_by => \&keyword, user_override => \&keyword);
use constant {
  SUBMITTED_YES=>"sub_yes", SUBMITTED_NO=>"sub_no", SUBMITTED_ANY=>"sub_any",
  SORT_ASSIGNMENT=>'sort_assignment', SORT_USER=>'sort_user',
  SORT_DATE=>'sort_date', SORT_NAME=>'sort_name' };

# Login
my ($tainted_user) = $config->user_override || $q->remote_user() =~ /^(\w+)\@/;

my $login = my $real_login = $config->users()->{$tainted_user};
panic("No such user: $tainted_user.", "Missing HTTPS?") unless defined $login;

if ($login->is_admin && user_override() ne "") {
  $login = $config->users()->{user_override()};
  panic("No such user for override: " . user_override()) unless $login;
}

my @all_users = $login->is_admin ?
  sort {$a->id cmp $b->id} values %{$config->users()} : ($login);
my @all_assignments =
  map { $config->assignment($_, @all_users); } dir_list($config->assignments_dir);

@all_assignments = grep { $_->hidden_until le $now } @all_assignments
  unless $login->is_admin;

# Other inputs
use constant {USERS => "users", ASSIGNMENTS => "assignments", FILE => 'file' };
my @users = select_by_id([values %{$config->users()}], $q->param(USERS));

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
      -uri=>url(SHOW_RESULTS(), 1, REPORTS(), reports(),
                ASSIGNMENTS, $assignment->id, USERS, $login->id,
                START_DATE(), $now, END_DATE(), $now));
}

sub main_view {
  my @rows;
  for my $assignment (@assignments) {
    my @shown_users = @users ? @users : @all_users;
    @shown_users = grep {same_group($assignment, $login, $_)} @shown_users
      unless $login->is_admin;
    for my $user (@shown_users) {
      my @dates = $assignment->submissions($user, show_group());
      @dates = grep {start_date() le $_->date} @dates if start_date();
      @dates = grep {end_date() ge $_->date} @dates if end_date();
      @dates = grep {not $_->failed} @dates if not show_failed();
      @dates = ($dates[$#dates]) if $#dates != -1 and only_latest();    

      push @rows, $assignment->no_submissions($user)
        if submitted() ne SUBMITTED_YES and not @dates;
      push @rows, @dates if submitted() ne SUBMITTED_NO;
    }
  }
  my %seen;
  @rows = grep { !$seen{$_->assignment->id."\x00".$_->user->id."\x00".$_->date}++} @rows;
# TODO

  @rows = sort {
    (sort_by() eq SORT_USER and $a->group_id cmp $b->group_id)
      or (sort_by() eq SORT_DATE and $a->date cmp $b->date)
      or (sort_by() eq SORT_NAME and $a->group_name cmp $b->group_name)
      or ($a->assignment->id cmp $b->assignment->id)
      or ($a->group_id cmp $b->group_id)
      or ($a->date cmp $b->date) } @rows;

  pre_body();

  if (show_submit_form()) {
    for my $a (@assignments) {
      say $q->start_div({-class=>'assignment'});
      say $q->h2($a->id . ": ", $a->title);
      say $q->h4("Due by ", pretty_date($a->due)) unless $a->due eq "";
      say $q->div(scalar(slurp(catfile($config->assignments_dir,                                       $a->text_file))))
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
    say $q->thead($q->Tr($q->th(["#", "Title", "User", "Name",
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
        my $num_files = @{$r->files} || 1;
        my @new_cells = (
          $r->assignment->id, $r->assignment->title,
          join("; ",map {$_->id.($_->is_admin?" (admin)":"")} @{$r->group}),
          join("; ",map {$_->name} @{$r->group}),
          ($r->date ?
           (href(url(@url, GUARDS(), 1, REPORTS(), 1, SHOW_RESULTS(), 1),
                 pretty_date($r->date) . ' [' . $r->user->id . ']') .
            ($r->late ? " (Late)" : "") . ($r->failed ? " - FAILED" : "")) :
           ("(Nothing submitted)")));

        my ($i) = firstidx {$_} pairwise {(not defined $a) or $a ne $b} @cells, @new_cells;
#        my $i = firstidx {(not defined $_->[0]) or $_->[0] ne $_->[1]} pairwise {[$a, $b]} @cells, @new_cells;
# TODO
 
        say "<tr><td class='indent' colspan='$i' rowspan='$num_files'></td>" if $i;
        say "<td rowspan='$num_files'>$_</td>" for @new_cells[$i..$#new_cells];

        my @file_rows = @{$r->files} ?
          map {[href(url(@url, DO_DOWNLOAD(), 1, FILE, $_->name), $_->name),
                $_->size] } @{$r->files} : ["(No files)", ""];
        say join("</tr><tr>", map {$q->td({-class=>'file'}, $_)} @file_rows);

        say "</tr>";
        @cells = @new_cells;

        if ($r->date and (reports() or guards())) {
          my @programs = ((guards() ? @{$r->assignment->guards} : ()),
                          (reports() ? @{$r->assignment->reports} : ()));
          say '<tr><td class="indent" colspan=2></td>';
          say '<td colspan=6 class="indent" style="background:rgb(95%,95%,95%);">';
          say 'Submission ', ($r->failed ? 'FAILED' : 'succeeded');
          say ' and is ', ($r->late ? 'LATE' : 'on time'), '.';
          say '</td></tr>';
          set_env($r->assignment, $r->user, $r->date);
          for my $program (@programs) {
            say "<tr><td class='indent' colspan=2></td><td class='indent' colspan=6><div>";
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
  print $q->header();
  say $q->start_html(-title=>"Error: " . $config->title);
  say $q->h1("Error: " . $config->title);
  say $q->p([@_, "(At line ".warn_at_line(@_)." and time ".tiro_date("now").".)"]);
  exit 0;
}

sub error { # Prints error with navigation components
  pre_body();
  say $q->h1({-style=>"color:red;"}, ["Error: ", @_]);
  say $q->p("(At line " . warn_at_line(@_) . " and time $now.)");
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
  .file+.file { text-align:right; }

  .results { width:100%; border-spacing: 0px; border-bottom:1px solid black; }
  .results>thead>TR>th { border-bottom:1px solid black; }

  .results>tbody>TR>td { border-top:solid 1px black; }
  .results>tbody>TR>td.indent { border-top: none; }

  .results>tbody>TR>td.file { border-top: none; }
  .results>tbody>TR>td+td.file { border-top:solid 1px black; }
  .results>tbody>TR>td.file+td.file { border-top:none; }
  .results>tbody>TR>td+td.file+td.file { border-top:solid 1px black; }

  .assignment { width:100%;border-bottom:1px solid black;margin-bottom:1.3em; }
  .body { margin-left:21em; }
  .footer { clear:left; text-align:right; font-size: small; }
  .welcome { float:right; font-weight:bold; }
  .hidden_until { color:red; }
EOT

  my $user_id = $login->id;
  if ($real_login->is_admin) {
    $user_id = $q->popup_menu(
      USER_OVERRIDE(), [sort keys %{$config->users()}], $login->id);
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
    my $num_users = keys %{$config->users()};
    my $late = ($a->late_if($now) and not any {not $_->late} @{$a->dates});
    say row(1, href(url(ASSIGNMENTS, $a->id, SHOW_GROUP(), 1, SHOW_RESULTS(), 1,
                        SHOW_SUBMIT_FORM(), 1), $a->id . ": ", $a->title),
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

  say $q->h3("... or", href(url(), "Start Over"));

  say $q->h3("... or", href(url(SHOW_SEARCH_FORM(), 1), "Search"));
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
      ["Status:", radio(SUBMITTED(),
                        [SUBMITTED_ANY, "Any"],
                        [SUBMITTED_YES, "Submitted"],
                        [SUBMITTED_NO, "Unsubmitted"])],
      ["Sort by:", radio(SORT_BY(),
                         [SORT_ASSIGNMENT, "Assignment"],
                         [SORT_USER, "User ID"],
                         [SORT_NAME, "User Name"],
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
  printf("<p class='footer'>Completed in %0.3f seconds by " .
         "<a href='http://www.cs.indiana.edu/~adamsmd/projects/tiro/'>" .
         "Tiro</a>.\n", time() - $start_time);
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

sub filename { catfile($config->submissions_dir, @_); }

sub select_by_id {
  my ($list1, @list2) = @_;
  my %a = map {($_,1)} @list2;
  sort {$a->id cmp $b->id} grep {$a{$_->id}} @{$list1}
}

################
# HTML Utils
################

sub define_param { # define_param(fun_name => \&filter_fun, ...)
  my (%hash) = @_;
  for my $key (keys %hash) {
    no strict 'refs';
    *$key = sub () { $hash{$key}->($q->param($key)); };
    *{uc $key} = sub () { $key; };
  }
}

sub url { # url(cgi_key, cgi_value, ...)
  my %args = @_;
  $args{USER_OVERRIDE()} = user_override() if $real_login->id ne $login->id;
  return "?" . join "&", map {"$_=$args{$_}"} keys %args;
}

sub multilist { # multilist(cgi_key, row1, row2, row3 ...)
  my $name = shift;
  $q->scrolling_list(
    -name=>$name, -multiple=>1, -size=>5, -values=>[@_], -default=>[@_]);
}

sub radio { # radio(cgi_key, [value, label], [value, label], ...)
  my $name = shift;
  scalar($q->radio_group(-columns=>1, -name=>$name, -labels=>{map { @$_ } @_},
                         -values=>[map { $_->[0] } @_]));
}

sub pretty_date { UnixDate($_[0], $config->date_format) }

sub href { my $href = shift; $q->a({-href=>$href}, @_); }

sub row { my $span = shift; $q->Tr($q->td({-colspan=>$span}, [@_])); }
