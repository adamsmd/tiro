#! /usr/bin/perl -T
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout
umask 0077; # Default to private files
delete @ENV{qw(PATH IFS CDPATH ENV BASH_ENV)}; # Make %ENV safer

# Configuration
my %config_hash = (
  # Bootstrap Configurations
  config_file=>'config/config.cfg',
  working_dir=>'.',

  # General Configurations
  # title => 'Assignment Submission Demo',
  path => '/usr/bin',
  max_post_size => 10000,
  date_format => '%a, %b %d %Y, %r',
  log_file => 'config/log.txt',

  # Assignment Configurations
  assignments_dir => 'assignments',
  assignments_regex => qr[^(\w+)\.cfg$],
  submissions_dir => 'submissions',

  # User Configurations
  #admins => ['user1'],
  #user_override => 'user1',
  #users => { user1 => { full_name => 'Demo User #1', expires=>'tomorrow'} },
  #users_file=>"users.csv",
  #user_name_column=>0, user_full_name_column=>1, user_expires_column=>2,
  #users_header_lines=>1,
  );

# Modules from Core
use CGI qw/-private_tempfiles -nosticky/;
use CGI::Carp qw/carpout/;
use Class::Struct;
use File::Copy qw/copy/; # NOTE: move() has tainting issues
use File::Path qw/mkpath/;
use File::Spec::Functions;
use Text::ParseWords;
use Time::HiRes qw/time/;
sub say { print @_, "\n"; } # Emulate Perl 6 feature

# Modules not from Core
use Date::Manip;
use File::Slurp qw/slurp/; # Perl 6 feature
use List::MoreUtils qw/:all/;

################
# Static Defs
################

# Structs
struct Config=>{
  config_file=>'$', working_dir=>'$', title=>'$', path=>'$',
  max_post_size=>'$', date_format=>'$', log_file=>'$', assignments_dir=>'$',
  assignments_regex=>'$', submissions_dir=>'$', admins=>'*@',
  user_override=>'$', users=>'*%', users_file=>'$',
  user_name_column=>'$', user_full_name_column=>'$', user_expires_column=>'$',
  users_header_lines=>'$', text=>'$' };
struct User=>{name => '$', full_name => '$', expires => '$'};
struct Assignment=>{
  name=>'$', path=>'$', dates=>'@', title=>'$', text=>'$', hidden_until=>'$',
  text_file=>'$', due=>'$', file_count=>'$', validators=>'@'};
struct Row=>{assignment=>'Assignment', user=>'User', date=>'$', files=>'@'};
struct File=>{name=>'$', size=>'$'};

defined $config_hash{$_} or $config_hash{$_} = ""
  for ('config_file', 'log_file', 'users_file', 'user_expires_column');

################
# Bootstrap
################

my $start_time = time();
my $config = Config->new(%config_hash);

if ($config->config_file ne "") {
  my $hash = parse_config($config->config_file, 'text', 'admins', 'users');
  $hash->{'users'} = { map { /\s*(.*?)\s*--\s*(.*?)\s*--\s*(.*)\s*/;
                             ($1, { full_name => $2, expires => $3 }) }
                       @{$hash->{'users'}} };
  %config_hash = (%config_hash, %{$hash});
  $config = Config->new(%config_hash);
}

chdir $config->working_dir or
  die "Can't chdir to working_dir ", $config->working_dir, ": $!";

if ($config->log_file ne "") {
  open(my $LOG_FILE, ">>" . $config->log_file) or
    die "Can't open log file ", $config->log_file, ": $!\n";
  carpout($LOG_FILE);
}

$CGI::POST_MAX = $config->max_post_size;
$ENV{PATH} = $config->path;
my $q = CGI->new;
die $q->cgi_error() if $q->cgi_error();

exists $ENV{$_} and warn("$_: ", $ENV{$_}) for
  ("REMOTE_HOST", "REMOTE_USER", "HTTP_REFERER", "HTTP_X_FORWARDED_FOR");
warn "Param $_: ", join(":",$q->param($_)) for $q->param();

if ($config->users_file ne "") {
  for (drop($config->users_header_lines || 0,
            split("\n", slurp $config->users_file))) {
    my @words = quotewords(",", 0, $_);
    my $name = $words[$config->user_name_column];
    my $full_name = $words[$config->user_full_name_column];
    my $expires = $config->user_expires_column eq "" ?
      'tomorrow' : $words[$config->user_expires_column];
    if (defined $name and defined $full_name and defined $expires) {
      $config_hash{'users'}->{$name} = {
        full_name => $full_name, expires => $expires };
    }
  }
  $config = Config->new(%config_hash);
}

################
# Parse Inputs
################

# Input formats
sub date { ((UnixDate($_[0], "%O") or "") =~ /^([A-Za-z0-9:-]+)$/)[0]; }
sub file { (($_[0] or "") =~ qr/^(?:.*\/)?([A-Za-z0-9_\. -]+)$/)[0]; }
sub keyword { (($_[0] or "") =~ qr/^([A-Za-z0-9]*)/)[0]; }
sub bool { $_[0] ? 1 : 0; }

# Basic Inputs
my $now = date "now";
define_param(
  start_date => \&date, end_date => \&date,
  do_search => \&bool, do_download => \&bool, do_upload => \&bool,
  do_upload_form => \&bool, do_results => \&bool,
  only_latest => \&bool, validation => \&bool,
  submitted => \&keyword, due => \&keyword, sort_by => \&keyword);
use constant {
  SUBMITTED_YES=>"sub_yes", SUBMITTED_NO=>"sub_no", SUBMITTED_ANY=>"sub_any",
  DUE_PAST=>'due_past', DUE_FUTURE=>'due_future', DUE_ANY=>'due_any',
  SORT_ASSIGNMENT=>'s_assignment', SORT_USER=>'s_user', SORT_DATE=>'s_date'};

# Complex Inputs
my ($tainted_user) = $config->user_override || $q->remote_user() =~ /^(\w+)\@/;
my $remote_user = file($tainted_user);
my $is_admin = any { $_ eq $remote_user } @{$config->admins};

use constant {USERS => "users", ASSIGNMENTS => "assignments", FILE => 'file' };

my @all_users = $is_admin ? sort keys %{$config->users} : ($remote_user);
@all_users = map { user($_) } @all_users;

my @users = $q->param(USERS) ? $q->param(USERS) : map {$_->name} @all_users;
@users = intersect(\@all_users, sub {$_[0]->name}, \@users);

my @all_assignments = list_assignments();
@all_assignments =
  grep { $is_admin or ($_->hidden_until || "") le $now } @all_assignments;

my @assignments = map { file $_ } $q->param(ASSIGNMENTS);
@assignments = intersect(\@all_assignments, sub {$_[0]->name}, \@assignments);
@assignments = grep {
  due() ne DUE_FUTURE and ($_->due eq "" or $_->due le $now) or
    due() ne DUE_PAST and ($_->due eq "" or $_->due gt $now) } @assignments;

my $file = file $q->param(FILE);
my @files = $q->upload(FILE);

################
# Main Code
################

error('Malformed remote user "' . $tainted_user . '".', "Missing .htaccess?")
  unless $remote_user;
error("No such user: $remote_user")
  unless defined $config->users->{$remote_user};
error("Access for $remote_user expired as of ", user($remote_user)->expires)
  unless $now lt date(user($remote_user)->expires);

if (do_download()) { download(); }
elsif (do_upload()) { upload(); }
else { render(search_results()); }
exit 0;

################
# Actions
################

sub error {
  print $q->header();
  say $q->start_html(-title=>$config->title . ": Error");
  say $q->h1($config->title . ": Error");
  my ($package, $filename, $line) = caller;
  say $q->p([@_, "(At line $line and time: " . $now . ")"]);
  exit 0;
}

sub download {
  @assignments and @users and start_date() and $file or
    error ("Invalid download request");
  my ($assignment, $user) = ($assignments[0]->name, $users[0]->name);
  my $path = filename($assignment, $user, start_date(), $file);
  -f $path and -r $path or
    error("Can't read $file in $assignment for $user at @{[start_date()]}");
  print $q->header(-type=>'application/octet-stream',
                   -attachment=>$file, -Content_length=>-s $path);
  copy($path, *STDOUT) or die "Failed to send download: ", $!;
}

sub upload {
  @files or error("No files selected for upload.");
  @files == uniq map { file $_ } @files or error("Duplicate file names.");
  my $assignment = $assignments[0] or error("No assignment for upload.");

  my $target_dir = filename($assignment->name, $remote_user, $now);
  warn "Starting upload of $_ in $target_dir" for @files;
  mkpath($target_dir) or error("Can't mkdir in @{[$assignment->name]} for " .
                               "$remote_user at $now: $!");
  foreach my $file (@files) {
    copy($file, catfile($target_dir, file $file)) or
      error("Can't save @{[file $file]} in @{[$assignment->name]} " .
            "for $remote_user at $now: $!");
  }
  warn "Upload done for $_ (@{[-s catfile($target_dir, $_)]} bytes)" .
    " in $target_dir" for dir_list($target_dir);
  print $q->redirect(
      -status=>303, # HTTP_SEE_OTHER
      -uri=>form_url(DO_RESULTS(), 1, VALIDATION(), validation(),
                     ASSIGNMENTS, $assignment->name, USERS, $remote_user,
                     START_DATE(), $now, END_DATE(), $now));
}

sub search_results {
  my @rows;
  foreach my $assignment (@assignments) {
    foreach my $user (@users) {
      my @dates = list_dates($assignment->name, $user->name);
      push @rows, Row->new(assignment=>$assignment, user=>$user,
                           date=>'', files=>[])
        if submitted() ne SUBMITTED_YES and not @dates;
      foreach (@dates) {
        push @rows, Row->new(assignment=>$assignment, user=>$user, date=>$_,
                             files=>[list_files($assignment, $user, $_)])
          if submitted() ne SUBMITTED_NO;
      }
    }
  }

  return sort {(sort_by() eq SORT_USER and $a->user->name cmp $b->user->name)
                 or (sort_by() eq SORT_DATE and $a->date cmp $b->date)
                 or ($a->assignment->name cmp $b->assignment->name)
                 or ($a->user->name cmp $b->user->name)
                 or ($a->date cmp $b->date) } @rows;
}

sub render {
  my (@rows) = @_;

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
  .results>tbody>TR:first-child>td+td+td+td+td+td+td { text-align:right; }
  .results>tbody>TR+TR>td+td { text-align:right; }
  .results>tbody>TR+TR>td+td[colspan] { text-align:left; }
  .assignment { width:100%;border-bottom:1px solid black;margin-bottom:1.3em; }
  .body { margin-left:21em; }
  .footer { clear:left; text-align:right; font-size: small; }
  .welcome { float:right; font-weight:bold; }
  .hidden_until { color:red; }
EOT

  say $q->div({-class=>'welcome'},
              "Welcome $remote_user<br>Current time is", pretty_date($now));
  say $q->h1($config->title);

  say $q->start_div({-class=>'navbar'});

  say $q->h3("Select Assignment");
  say $q->start_table();
  foreach my $assignment (@all_assignments) {
    my $num_done = (grep { @$_ } @{$assignment->dates});
    my $num_users = @all_users;
    my $late = ($assignment->due ne "" and ($now ge $assignment->due)
                and not (any {$_ le $assignment->due} $assignment->dates));
    say row(0, 1, href(form_url(DO_UPLOAD_FORM(), 1, DO_RESULTS(), 1,
                                ASSIGNMENTS, $assignment->name),
                       $assignment->name . ": ", $assignment->title),
            ($num_done ? "&nbsp;&#x2611;" : "&nbsp;&#x2610;") .
            ($is_admin ? $q->small("&nbsp;($num_done/$num_users)") : "") .
            ($late ? "&nbsp;Late" : ""));
    say row(0, 2, $q->small("&nbsp;&nbsp;Due " . pretty_date($assignment->due)))
      unless $assignment->due eq "";
    say row(0, 2, $q->small({-class=>'hidden_until'},
                            "&nbsp;&nbsp;Hidden until " .
                            pretty_date($assignment->hidden_until)))
      unless $assignment->hidden_until lt $now;
  }
  say row(0, 1, "(No assignments yet)") unless @all_assignments;
  say $q->end_table();

  say $q->h3("... or", href(form_url(), "Start Over"));

  say $q->h3("... or", href(form_url(DO_SEARCH(), 1), "Search"));
  if (do_search()) {
    say $q->start_form(-action=>'#', -method=>'GET');
    say $q->hidden(-name=>DO_SEARCH(), -default=>1);
    say $q->hidden(-name=>DO_RESULTS(), -default=>1);
    say $q->start_table({-class=>'search'});
    map { say row(0, 1, @$_) } (
      ["User:", multilist(USERS, map {$_->name} @all_users)],
      ["Assignment:", multilist(ASSIGNMENTS, map {$_->name} @all_assignments)],
      ["Show:", boxes([ONLY_LATEST(), only_latest(), 'Only Most Recent'],
                      [DO_UPLOAD_FORM(), do_upload_form(), 'Upload Form'],
                      [VALIDATION(), validation(), 'Validation'])],
      ["", $q->submit(-value=>"Search")],
      ["","&nbsp;"],
      ["<b>Advanced</b>", ""],
      ["Start date:", $q->textfield(-name=>START_DATE(), -value=>'Any')],
      ["End date:", $q->textfield(-name=>END_DATE(), -value=>'Any')],
      ["Status:", radio(SUBMITTED(), 0,
                        [SUBMITTED_ANY, "Any"],
                        [SUBMITTED_YES, "Submitted"],
                        [SUBMITTED_NO, "Unsubmitted"])],
      ["Due:", radio(DUE(), 0,
                     [DUE_ANY, "Any"],
                     [DUE_PAST, "Past"],
                     [DUE_FUTURE, "Future"])],
      ["Sort by:", radio(SORT_BY(), 0,
                         [SORT_ASSIGNMENT, "Assignment"],
                         [SORT_USER, "User"],
                         [SORT_DATE, "Date"])],
      ["", $q->submit(-value=>"Search")]);
    say $q->end_table();
    say $q->end_form();
  }
  say $q->end_div();

  say $q->start_div({-class=>'body'});
  if (do_upload_form()) {
    foreach my $assignment (@assignments) {
      say $q->start_div({-class=>'assignment'});
      say $q->h2($assignment->name . ": ", $assignment->title);
      say $q->h4("Due by ", pretty_date($assignment->due))
        unless $assignment->due eq "";
      say $q->div(scalar(slurp(catfile($config->assignments_dir,
                                       $assignment->text_file))))
        unless $assignment->text_file eq "";
      say $q->div($assignment->text)
        unless $assignment->text eq "";

      if ($assignment->file_count ne "") {
        say $q->start_form(
          -method=>'POST', -enctype=>&CGI::MULTIPART, -action=>'#');
        say $q->hidden(
          -name=>ASSIGNMENTS, -value=>$assignment->name, -override=>1);
        say $q->hidden(-name=>VALIDATION(), -value=>1, -override=>1);
        say $q->p("File $_:", $q->filefield(-name=>FILE, -override=>1))
          for (1..$assignment->file_count);
        say $q->p($q->submit(DO_UPLOAD(), "Submit"));
        say $q->end_form();
      }
      say $q->p(); # Add extra space before the final line
      say $q->end_div();
    }
  }

  if (do_results()) {
    say $q->start_table({-class=>'results'});
    say $q->thead($q->Tr($q->th(["#", "Title", "User"," Name", "Validation",
                                 "Files", "Bytes"])));
    if (not @rows) {
      say row(0, 7, $q->center('No results to display.',
                               'Browse or search to select assignment.'));
    } else {
      foreach my $row (@rows) {
        say $q->start_tbody();
        my @url = (ASSIGNMENTS, $row->assignment->name, USERS, $row->user->name,
                   START_DATE(), $row->date, END_DATE(), $row->date);
        my @file_rows = @{$row->files} ?
          map {[href(form_url(@url,DO_DOWNLOAD(),1,FILE,$_->name), $_->name),
                $_->size] } @{$row->files} : ["(No files)", ""];
        say multirow([$row->assignment->name, $row->assignment->title,
                      $row->user->name, $row->user->full_name,
                      ($row->date ?
                       (href(form_url(@url, VALIDATION(), 1, DO_RESULTS(), 1),
                             pretty_date($row->date))) :
                       ("(Nothing submitted)"))], @file_rows);

        if (validation() and $row->date) {
          if (not @{$row->assignment->validators}) {
            say '<tr><td></td>';
            say '<td colspan=7 style="background:rgb(95%,95%,95%);">';
            say "Submission received on @{[pretty_date($row->date)]}.";
            say '</td></tr>';
          } else {
            $ENV{'TIRO_SUBMISSION'} = filename(
              $row->assignment->name, $row->user->name, $row->date);
            $ENV{'TIRO_ASSIGNMENT'} = catfile(
              $config->assignments_dir, $row->assignment->path);
            for my $validator (@{$row->assignment->validators}) {
              say "<tr><td></td><td colspan=7><div>";
              warn "Running: $validator";
              system $validator;
              warn "Exit code: $?";
              say "</div></td></tr>";
            }
          }
        }
        say $q->end_tbody();
      }
    }
    say $q->end_table();
  }

  if (not do_upload_form() and not do_results()) {
    say $config->text;
  }
  say $q->end_div();

  say $q->p({-class=>'footer'}, "Completed in",
            sprintf("%0.3f", time() - $start_time), "seconds by",
            $q->a({-href=>'http://www.cs.indiana.edu/~adamsmd/projects/tiro/'},
                  "Tiro") . ".");
  say $q->end_html();
}

################
# Listings
################

sub list_assignments {
  map { my $path = $_;
        my ($name) = $_ =~ $config->assignments_regex;
        if (not defined $name) { (); }
        else {
          my $hash = parse_config(catfile($config->assignments_dir, $path),
                                  'text', 'validators');
          $hash->{'due'} = date($hash->{'due'});
          $hash->{'hidden_until'} = date($hash->{'hidden_until'});
          defined $hash->{$_} or $hash->{$_} = ""
            for ('due', 'hidden_until', 'text_file', 'text', 'file_count');
          Assignment->new(
            dates=> [map {[list_dates($name, $_->name, 1)]} @all_users],
            name=> $name, path=> $path, %{$hash});
        }
  } dir_list($config->assignments_dir);
}

sub user { User->new(name => $_[0], %{$config->users->{$_[0]}}) }

sub list_dates {
  my ($assignment, $user, $all) = @_;
  my @dates = map { date $_ } dir_list(
    $config->submissions_dir, $assignment, $user);
  @dates = grep { -d filename($assignment, $user, $_) } @dates;
  @dates = grep {start_date() le $_} @dates if not $all and start_date();
  @dates = grep {end_date() ge $_} @dates if not $all and end_date();
  @dates = ($dates[$#dates]) if !$all and $#dates != -1 and only_latest();    
  return @dates;
}

sub list_files {
  my ($assignment, $user, $date) = @_;
  my @names = dir_list($config->submissions_dir,
                       $assignment->name, $user->name, $date);
  map { File->new(name=>$_, size=>-s filename(
                    $assignment->name,$user->name,$date,$_)) } @names;
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

sub form_url { my %args = @_; "?" . join "&", map {"$_=$args{$_}"} keys %args }

sub pretty_date { UnixDate($_[0], $config->date_format) }

sub href { my ($href, @rest) = @_; $q->a({-href=>$href}, @rest); }

sub multilist {
  $q->scrolling_list(-name=>$_[0], -multiple=>1, -size=>5,
                     -values=>[@_[1..$#_]], -default=>[@_[1..$#_]]);
}

sub boxes {
  join $q->br(), map { $q->checkbox($_->[0], $_->[1], 'on', $_->[2]) } @_;
}

sub radio {
  my ($name, $def, @rest) = @_;
  scalar($q->radio_group(-columns=>1, -name=>$name, -default=>$rest[$def][0],
                         -values=>[map { $_->[0] } @rest],
                         -labels=>{map { @$_ } @rest}));
}

sub row {
  my ($pre, $span, @data) = @_;
  $q->Tr(($pre ? $q->td({-colspan=>$pre}) : ()),
         $q->td({-colspan=>$span}, [@data]))
}

sub multirow {
  my ($prefix, @rows) = @_;
  "<tr>" . $q->td({-rowspan=>scalar(@rows)}, $prefix) .
    join("</tr><tr>", (map { $q->td($_) } @rows)) . "</tr>";
}

################
# General Utils
################

sub drop { @_[$_[0]+1..$#_] }

sub intersect {
  my ($list1, $fun, $list2) = @_;
  my %a = map {($_,1)} @{$_[2]};
  sort {&$fun($a) cmp &$fun($b)} grep {$a{$_[1]->($_)}} @{$_[0]}
}

sub dir_list {
  opendir(my $d, catdir(@_)) or return ();
  my @ds = readdir($d);
  closedir $d;
  return sort grep {!/^\./} @ds; # skip dot files
}

sub parse_config {
  my ($filename, $body_name, @lists) = @_;
  my ($lines, $body) = slurp($filename) =~ /^(.*?)(?:\n\s*\n\s*(.*))?$/s;
  my %hash = map { ($_, []) } @lists;
  for (split "\n", $lines) {
    my ($key, $value) = /^\s*([^:]*?)\s*:\s*(.*?)\s*$/;
    if (defined $key and defined $value) {
      if (grep { $_ eq $key } @lists) {
        push @{$hash{$key}}, $value;
      } else {
        $hash{$key} = $value;
      }
    }
  }
  $hash{$body_name} = ($hash{$body_name} || "") . ($body || "");
  return \%hash;
}
