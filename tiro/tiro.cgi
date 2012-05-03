#! /usr/bin/perl -T
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout
umask 0077; # Default to private files
delete @ENV{qw(PATH IFS CDPATH ENV BASH_ENV)}; # Make %ENV safer

# Configuration
use constant CONFIG_FILE => 'system/tiro.cfg';
use lib 'system/lib';

# Modules from Core
use Archive::Tar;
use Carp qw(verbose);
use CGI qw(-private_tempfiles -nosticky);
use CGI::Carp qw(carpout set_progname);
use Class::Struct;
use File::Copy qw(copy move); # NOTE: move() has tainting issues
use File::Path qw(mkpath);
use File::Spec::Functions;
use IO::Compress::Gzip qw(gzip $GzipError);
use Time::HiRes qw(time);
sub say { print @_, "\n"; } # Emulate Perl 6 feature

# Modules not from Core
use Tiro;
use Date::Manip;
use File::Slurp qw/slurp/; # Perl 6 feature
use List::MoreUtils qw/:all/;

################
# Bootstrap
################

my $start_time = time(); # For measuring how long Tiro runs
my $now = tiro_date "now"; # When Tiro started (e.g. submission date)

set_progname("tiro.cgi (PID:$$ USER:$ENV{'REMOTE_USER'})"); # Warning Prefix

# TODO: if ! -f CONFIG_FILE: can't load global config, copy tiro.cfg.sample?
my $tiro = Tiro->new(CONFIG_FILE);

if ($tiro->log_file ne "") {
  open(my $LOG_FILE, ">>" . UnixDate("now", $tiro->log_file)) or
    die "Can't open log file ", $tiro->log_file, ": $!\n";
  carpout($LOG_FILE);
}

warn "+++ Starting tiro.cgi +++";
END { warn "--- Stopping tiro.cgi ---"; }

$CGI::POST_MAX = $tiro->max_post_size;
$ENV{PATH} = $tiro->path;
my $q = CGI->new;
panic("Connection limit (@{[$tiro->max_post_size]} bytes) exceeded.",
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
define_param(
  do_download => \&bool, do_download_archive => \&bool, do_submit => \&bool,
  show_search_form => \&bool, show_assignments => \&bool,
  show_submissions => \&bool, show_failed => \&bool, show_group => \&bool,
  start_date => \&tiro_date, end_date => \&tiro_date, only_latest => \&bool,
  reports => \&bool, guards => \&bool, submitted => \&keyword,
  sort_by => \&keyword, user_override => \&keyword);
use constant {
  SUBMITTED_YES=>"sub_yes", SUBMITTED_NO=>"sub_no", SUBMITTED_ANY=>"sub_any",
  SORT_ASSIGNMENT=>'sort_assignment', SORT_USER=>'sort_user',
  SORT_DATE=>'sort_date', SORT_NAME=>'sort_name' };

# Login
my ($tainted_user) = $tiro->user_override || $q->remote_user() =~ /^(\w+)\@/;

my $login = my $real_login = $tiro->users()->{$tainted_user};
panic("No such user: $tainted_user.", "Missing HTTPS?") unless defined $login;

if ($login->is_admin && user_override() ne "") {
  $login = $tiro->users()->{user_override()};
  panic("No such user for override: " . user_override()) unless $login;
}

my @all_users = $login->is_admin ?
  sort {$a->id cmp $b->id} values %{$tiro->users()} : ($login);
my @all_assignments =
  map { $tiro->assignment($_, @all_users); } dir_list($tiro->assignments_dir);

@all_assignments = grep { $_->hidden_until le $now } @all_assignments
  unless $login->is_admin;

# Other inputs
use constant {USERS => "users", ASSIGNMENTS => "assignments", FILE => 'file' };
my @users = select_by_id(\@all_users, $q->param(USERS));

my @assignments = select_by_id(
  \@all_assignments, map { file $_ } $q->param(ASSIGNMENTS));

my $download = file $q->param(FILE);
struct UploadFile=>{name=>'$', handle=>'$'};
my @upload_files =
  map {UploadFile->new(name=>file($_), handle=>$_)} ($q->upload(FILE));

$ENV{'TZ'} = Date_TimeZone(); # make reports see the timezone

################
# Main Code
################

error('Invalid file names (only "A-Za-z0-9_. -" characters allowed): ',
      join(", ", $q->param(FILE)))
  unless not any { not defined $_->name } @upload_files;
{ my @x = map { $_->name } @upload_files;
  error('Duplicate file names: ', join(", ", @x)) unless @x == uniq @x; }

if (do_download()) { download(); }
elsif (do_download_archive()) { download_archive(); }
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
  print $q->header(-Content_length=>-s $path,
                   ($download =~ $assignments[0]->download_inline) ?
                   (-type=>'text/plain',
                    -Content_disposition=>"inline; filename=\"$download\"") :
                   (-type=>'application/octet-stream',
                    -attachment=>$download));
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
      -uri=>url(SHOW_SUBMISSIONS(), 1, REPORTS(), reports(),
                ASSIGNMENTS, $assignment->id, USERS, $login->id,
                START_DATE(), $now, END_DATE(), $now));
}

sub get_subs {
  return $tiro->query(
    assignments=>[@assignments], users=>[@users ? @users : @all_users],
    login=>$login, groups=>scalar show_group(),
    start_date=>scalar start_date(), end_date=>scalar end_date(),
    failed=>scalar show_failed(), only_latest=>scalar only_latest(),
    submissions_no=>(submitted() ne SUBMITTED_YES),
    submissions_yes=>(submitted() ne SUBMITTED_NO));
}

sub download_archive {
  my $tar = Archive::Tar->new();
  for my $submission (get_subs()) {
    for my $file (@{$submission->files}) {
      $tar->add_data(catfile('submissions', $submission->assignment->id,
                             join('-', map {$_->id} @{$submission->group}),
                             $submission->date . $submission->failed,
                             $file->name),
                     slurp filename($submission->assignment->id,
                                    $submission->user->id,
                                    $submission->date . $submission->failed,
                                    $file->name))
        or panic("Failed to compress " . $file->name .
                 " in " . $submission->assignment->id .
                 " for ". $submission->user->id . " at " . $submission->date);
    }
  }

  my ($tar_data, $gzip_data) = $tar->write();
  gzip \$tar_data => \$gzip_data or panic("gzip failed: $GzipError");
  print $q->header(-type=>'application/zip', -attachment=>'submissions.tar.gz',
                   -Content_length=>length $gzip_data);
  print $gzip_data;
}

sub main_view {
  my @subs = sort {
    (sort_by() eq SORT_USER and $a->group_id cmp $b->group_id)
      or (sort_by() eq SORT_DATE and $a->date cmp $b->date)
      or (sort_by() eq SORT_NAME and $a->group_name cmp $b->group_name)
      or (cmp_alphanum($a->assignment->id, $b->assignment->id))
      or ($a->group_id cmp $b->group_id)
      or ($a->date cmp $b->date) } get_subs();

  pre_body();

  if (show_assignments()) {
    say "<div class='assignments'>";
    for my $a (@assignments) {
      say $q->start_div({-class=>'assignment'});
      say $q->h2($a->id . ": ", $a->title);
      say $q->h4("Due by ", pretty_date($a->due)) unless $a->due eq "";
      say $q->div(scalar(slurp(catfile($tiro->assignments_dir, $a->text_file))))
        unless $a->text_file eq "";
      say $q->div({-class=>'assignment_div'}, $a->text) unless $a->text eq "";

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
    say "</div>";
  }

  if (show_submissions()) {
    say $q->start_table({-class=>'submissions'});
    say $q->thead($q->Tr($q->th(["#", "Title", "User", "Name",
                                 "Reports", "Files", "Bytes"])));
    if (not @subs) {
      say row(7, $q->center('No submissions to display.',
                            'Browse or search to select assignment.'));
    } else {
      my @cells = ();
      for my $s (@subs) {
        my @url = (ASSIGNMENTS, $s->assignment->id, USERS, $s->user->id,
                   START_DATE(), $s->date, END_DATE(), $s->date,
                   SHOW_FAILED(), $s->failed);
        my $num_files = @{$s->files} || 1;
        my @new_cells = (
          $s->assignment->id, $s->assignment->title,
          join("; ",map {$_->id.($_->is_admin?" (admin)":"")} @{$s->group}),
          join("; ",map {$_->name} @{$s->group}),
          ($s->date ?
           (href(url(@url, GUARDS(), 1, REPORTS(), 1, SHOW_SUBMISSIONS(), 1),
                 pretty_date($s->date) . ' by ' . $s->user->id) .
            ($s->late ? " (Late)" : "") . ($s->failed ? " - FAILED" : "")) :
           ("(Nothing submitted)")));

        my ($i) = firstidx {$_} pairwise {(not defined $a) or $a ne $b} @cells, @new_cells;
# TODO
 
        say "<tr class='submission'>";
        say "<td class='indent' colspan='$i' rowspan='$num_files'></td>" if $i;
        say "<td rowspan='$num_files'>$_</td>" for @new_cells[$i..$#new_cells];

        say join("</tr><tr class='submission_file'>",
                 map {$q->td({-class=>'file'}, $_)}
                 (@{$s->files} ?
                  map {[href(url(@url, DO_DOWNLOAD(), 1, FILE, $_->name),
                             $_->name), $_->size] } @{$s->files} :
                  ["(No files)", ""]));

        say "</tr>";
        @cells = @new_cells;

        if ($s->date and (reports() or guards())) {
          my @programs = ((guards() ? @{$s->assignment->guards} : ()),
                          (reports() ? @{$s->assignment->reports} : ()));
          say '<tr class="report_row"><td class="indent" colspan=2></td>';
          say '<td colspan=6 style="background:rgb(95%,95%,95%);">';
          say 'Submission ', ($s->failed ? 'FAILED' : 'succeeded');
          say ' and is ', ($s->late ? 'LATE' : 'on time'), '.';
          say '</td></tr>';
          set_env($s->assignment, $s->user, $s->date);
          for my $program (@programs) {
            say "<tr class='report_row'><td class='indent' colspan=2></td><td colspan=6><div class='report_div'>";
            warn "Running guard or report: $program";
            system $program;
            warn "Exit code: $?";
            say "</div></td></tr>";
          }
        }
      }
    }
    say $q->end_table();
    say $q->small(href(url($q->Vars, DO_DOWNLOAD_ARCHIVE(), 1),
                       "Archive of listed files"));
  }

  say $tiro->text if not show_assignments() and not show_submissions();
  post_body();
}

################
# Rendering Functions
################

sub warn_at_line { my $x = (caller(1))[2]; warn @_, " at line $x.\n"; $x }

sub panic { # Prints error without navigation components
  print $q->header(-charset=>'utf8');
  say $q->start_html(-title=>"Error: " . $tiro->title, -encoding=>'utf8');
  say $q->h1("Error: " . $tiro->title);
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
  print $q->header(-encoding=>'utf8');
  
  say $q->start_html(-title=>$tiro->title, -encoding=>'utf8',
                     -style=>{-verbatim=><<'EOT'});

  th { vertical-align:top; text-align:left; }
  td { vertical-align:top; text-align:left; }
  h2 { border-bottom:2px solid black; }

  .welcome { float:right; font-weight:bold; }
  .navbar { padding:0.3em; width:19em; float:left; border:solid black 1px; }
  .body { margin-left:21em; }
  .footer { clear:left; text-align:right; font-size: small; }

  .navbar table { width:100%; }
  .navbar td { vertical-align: baseline; }
  .navbar form td { vertical-align: top; }
  .navbar>h3:first-child { margin-top:0; } /* Stop spurious margin */
  .navbar .search { width:100%; }
  .navbar .search select { width:100%; }
  .navbar .search input[type="text"] { width:90%; }
  .navbar .hidden_until { color:red; }

  .assignment { width:100%;border-bottom:1px solid black;margin-bottom:1.3em; }
  .submissions { width:100%; border-spacing: 0px; border-bottom:2px solid black; }
  .submissions>thead>TR>th { border-bottom:1px solid black; }

  .submissions>tbody>TR>td { border-top:solid 1px black; }
  .submissions>tbody>TR>td.indent { border-top: none; }

  .submissions>tbody>TR.report_row>td { border-top: none; }

  .submissions>tbody>TR>td.file { border-top: none; }
  .submissions>tbody>TR>td+td.file { border-top:solid 1px black; }
  .submissions>tbody>TR>td.file+td.file { border-top:none; text-align: right; }
  .submissions>tbody>TR>td+td.file+td.file { border-top:solid 1px black; text-align: right; }

EOT

  my $user_id = $login->id;
  if ($real_login->is_admin) {
    $user_id = $q->popup_menu(
      USER_OVERRIDE(), [sort keys %{$tiro->users()}], $login->id);
    $user_id .= $q->submit(-value=>'Change user');
    for ($q->param) {
      $user_id .= "\n" . $q->hidden(-name=>$_, -default=>$q->param($_))
        if $_ ne FILE() and $_ ne USER_OVERRIDE();
    }
  }

  say $q->div({-class=>'welcome'},
              $q->start_form(-action=>"?".$q->query_string, -method=>'GET'),
              "Welcome $user_id<br>Current time is", pretty_date($now),
              $q->end_form());

  say $q->div({-class=>'header'}, $q->h1($tiro->title));

  say $q->start_div({-class=>'navbar'});

  say $q->h3("Select Assignment");
  say $q->start_table({-class=>'assignment_table'});
  for my $a (@all_assignments) {
    my $num_done = $a->num_late + $a->num_ontime;
    my $num_users = keys %{$tiro->users()};
    my $late = ($a->late_if($now) and $a->num_ontime == 0);
    say row(1, href(url(ASSIGNMENTS, $a->id, SHOW_GROUP(), 1,
                        SHOW_SUBMISSIONS(), 1, SHOW_ASSIGNMENTS(), 1),
                    $a->id . ": ", $a->title),
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
    say $q->start_form(-class=>'search_table', -action=>'#', -method=>'GET');
    say $q->hidden(-name=>USER_OVERRIDE(), -default=>user_override());
    say map {$q->hidden(-name=>$_, -default=>1)} (
      SHOW_SEARCH_FORM(), SHOW_SUBMISSIONS(), SHOW_GROUP());
    say $q->start_table({-class=>'search'});
    map { say row(1, @$_) } (
      ["User:", multilist(USERS, map {$_->id} @all_users)],
      ["Assignment:", multilist(ASSIGNMENTS, map {$_->id} @all_assignments)],
      ["Show:", join($q->br(), map {$q->checkbox($_->[0],$_->[1],'y',$_->[2])}
                     ([ONLY_LATEST(), only_latest(), 'Only Most Recent'],
                      [SHOW_ASSIGNMENTS(), show_assignments(), 'Submit Form'],
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
  warn "Processing " . $assignment->id . " for " . $user->id . " at " . $date;
  $ENV{'TIRO_CONFIG_FILE'} = CONFIG_FILE;
  $ENV{'TIRO_LOGIN_ID'} = $login->id;
  $ENV{'TIRO_LOGIN_IS_ADMIN'} = $login->is_admin;
  $ENV{'TIRO_REAL_LOGIN_ID'} = $real_login->id;
  $ENV{'TIRO_REAL_LOGIN_IS_ADMIN'} = $real_login->is_admin;

  $ENV{'TIRO_SUBMISSION_DIR'} = filename($assignment->id, $user->id, $date);
  $ENV{'TIRO_SUBMISSION_USER'} = $user->id;
  $ENV{'TIRO_SUBMISSION_DATE'} = $date;
  $ENV{'TIRO_ASSIGNMENT_FILE'} = catfile($tiro->assignments_dir,
                                         $assignment->path);

  $ENV{'TIRO_ASSIGNMENT_ID'} = $assignment->id;
  $ENV{'TIRO_ASSIGNMENT_TITLE'} = $assignment->title;
  $ENV{'TIRO_ASSIGNMENT_LATE_AFTER'} = $assignment->late_after;
  $ENV{'TIRO_ASSIGNMENT_DUE'} = $assignment->due;
  $ENV{'TIRO_ASSIGNMENT_FILE_COUNT'} = $assignment->file_count;
}

sub filename { catfile($tiro->submissions_dir, @_); }

sub select_by_id {
  my ($list1, @list2) = @_;
  my %a = map {($_,1)} @list2;
  grep {$a{$_->id}} @{$list1}
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

sub pretty_date { UnixDate($_[0], $tiro->date_format) }

sub href { my $href = shift; $q->a({-href=>$href}, @_); }

sub row { my $span = shift; $q->Tr($q->td({-colspan=>$span}, [@_])); }
