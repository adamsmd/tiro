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
use CGI qw/-private_tempfiles -nosticky/;
use CGI::Carp qw/carpout/;
use Class::Struct;
use File::Copy qw/copy/; # NOTE: move() has tainting issues
use File::Path qw/mkpath/;
use File::Spec::Functions;
use Time::HiRes qw/time/;
sub say { print @_, "\n"; } # Emulate Perl 6 feature

# Modules not from Core
use Tiro::Config;
use Date::Manip;
use File::Slurp qw/slurp/; # Perl 6 feature
use List::MoreUtils qw/:all/;

################
# Structs
################

struct Row=>{
  assignment=>'AssignmentConfig', user=>'UserConfig', date=>'$', files=>'@'};
struct File=>{name=>'$', size=>'$'};
struct Upload=>{name=>'$', handle=>'$'};

################
# Bootstrap
################

my $start_time = time();

my $config = parse_global_config_file(CONFIG_FILE);

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

my @all_users = sort {$a->name cmp $b->name} parse_user_configs($config);

################
# Input Parsing
################

# Input formats
sub date { ((UnixDate($_[0], "%O") or "") =~ m[^([A-Za-z0-9:-]+)$])[0]; }
sub file { (($_[0] or "") =~ m[^(?:.*/)?([A-Za-z0-9_\. -]+)$])[0]; }
sub keyword { (($_[0] or "") =~ m[^([A-Za-z0-9_]*)$])[0]; }
sub bool { $_[0] ? 1 : 0; }

# Basic Inputs
my $now = date "now";
define_param(
  do_search => \&bool, do_download => \&bool, do_upload => \&bool,
  do_upload_form => \&bool, do_results => \&bool,
  start_date => \&date, end_date => \&date,
  only_latest => \&bool, validation => \&bool,
  submitted => \&keyword, sort_by => \&keyword);
use constant {
  SUBMITTED_YES=>"sub_yes", SUBMITTED_NO=>"sub_no", SUBMITTED_ANY=>"sub_any",
  SORT_ASSIGNMENT=>'sort_assignment', SORT_USER=>'sort_user',
  SORT_DATE=>'sort_date', SORT_FULL_NAME=>'sort_full_name'};

# Complex Inputs
my ($tainted_user) = $config->user_override || $q->remote_user() =~ /^(\w+)\@/;
my $remote_user = file($tainted_user);
my $is_admin = any { $_ eq $remote_user } @{$config->admins};

use constant {USERS => "users", ASSIGNMENTS => "assignments", FILE => 'file' };

my ($remote_user_config) = grep {$_->name eq $remote_user} @all_users;
@all_users = $is_admin ? @all_users : ($remote_user_config);

my @users = $q->param(USERS) ? $q->param(USERS) : map {$_->name} @all_users;
@users = intersect(\@all_users, sub {$_[0]->name}, \@users);

my @all_assignments = list_assignments();
@all_assignments =
  grep { $is_admin or ($_->hidden_until || "") le $now } @all_assignments;

my @assignments = map { file $_ } $q->param(ASSIGNMENTS);
@assignments = intersect(\@all_assignments, sub {$_[0]->name}, \@assignments);

my $download = file $q->param(FILE);
my @uploads = map {Upload->new(name=>file($_), handle=>$_)} ($q->upload(FILE));

################
# Main Code
################

error('Malformed remote user "' . $tainted_user . '".', "Missing .htaccess?")
  unless $remote_user;
error("No such user: $remote_user")
  unless defined $config->users->{$remote_user};
error("Access for $remote_user expired as of ", $remote_user_config->expires)
  unless $now lt date($remote_user_config->expires);
error("Invalid file names: ", $q->param(FILE))
  unless not any { not defined $_->name } @uploads;
error("Duplicate file names: ", map { $_->name } @uploads)
  unless (map { $_->name } @uploads) == (uniq map { $_->name } @uploads);

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
  say $q->p([@_, "(At line $line and time $now.)"]);
  exit 0;
}

sub download {
  @assignments or error("No assignment for download");
  @users or error("No user for download");
  start_date() or error("No date for download");
  defined $download or error("No file for download");
  my ($assignment, $user) = ($assignments[0]->name, $users[0]->name);
  my $path = filename($assignment, $user, start_date(), $download);
  -f $path and -r $path or
    error("Can't read $download in $assignment for $user at @{[start_date()]}");
  print $q->header(-type=>'application/octet-stream',
                   -attachment=>$download, -Content_length=>-s $path);
  copy($path, *STDOUT) or die "Failed to send download: ", $!;
}

sub upload {
  @uploads or error("No files selected for upload.");
  my $assignment = $assignments[0] or error("No assignment for upload.");

  my $target_dir = filename($assignment->name, $remote_user, $now);
  warn "Starting upload of $_ in $target_dir" for @uploads;
  mkpath($target_dir) or error("Can't mkdir in @{[$assignment->name]} for " .
                               "$remote_user at $now: $!");
  foreach my $upload (@uploads) {
    copy($upload->handle, catfile($target_dir, $upload->name)) or
      error("Can't save @{[$upload->name]} in @{[$assignment->name]} " .
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
                 or (sort_by() eq SORT_FULL_NAME
                     and $a->user->full_name cmp $b->user->full_name)
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
  foreach my $a (@all_assignments) {
    my $num_done = (grep { @$_ } @{$a->dates});
    my $num_users = @all_users;
    my $late = ($a->due ne "" and ($now ge $a->due) and
                not any {any {$_ le $a->due} @$_} @{$a->dates});
    say row(0, 1, href(form_url(DO_UPLOAD_FORM(), 1, DO_RESULTS(), 1,
                                ASSIGNMENTS, $a->name),
                       $a->name . ": ", $a->title),
            ($num_done ? "&nbsp;&#x2611;" : "&nbsp;&#x2610;") .
            ($is_admin ? $q->small("&nbsp;($num_done/$num_users)") : "") .
            ($late ? "&nbsp;Late" : ""));
    say row(0, 2, $q->small("&nbsp;&nbsp;Due " . pretty_date($a->due)))
      unless $a->due eq "";
    say row(0, 2, $q->small({-class=>'hidden_until'},
                            "&nbsp;&nbsp;Hidden until " .
                            pretty_date($a->hidden_until)))
      unless $a->hidden_until lt $now;
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
  if (do_upload_form()) {
    foreach my $a (@assignments) {
      say $q->start_div({-class=>'assignment'});
      say $q->h2($a->name . ": ", $a->title);
      say $q->h4("Due by ", pretty_date($a->due)) unless $a->due eq "";
      say $q->div(scalar(slurp(catfile($config->assignments_dir,
                                       $a->text_file))))
        unless $a->text_file eq "";
      say $q->div($a->text) unless $a->text eq "";

      if ($a->file_count ne "") {
        say $q->start_form(
          -method=>'POST', -enctype=>&CGI::MULTIPART, -action=>'#');
        say $q->hidden(-name=>ASSIGNMENTS, -value=>$a->name, -override=>1);
        say $q->hidden(-name=>VALIDATION(), -value=>1, -override=>1);
        say $q->p("File $_:", $q->filefield(-name=>FILE, -override=>1))
          for (1..$a->file_count);
        say $q->p($q->submit(DO_UPLOAD(), "Submit"));
        say $q->end_form();
      }
      say $q->p(); # Add extra space before the final line
      say $q->end_div();
    }
  }

  if (do_results()) {
    say $q->start_table({-class=>'results'});
    say $q->thead($q->Tr($q->th(["#", "Title", "User"," Name",
                                 "Validation", "Files", "Bytes"])));
    if (not @rows) {
      say row(0, 7, $q->center('No results to display.',
                               'Browse or search to select assignment.'));
    } else {
      foreach my $r (@rows) {
        say $q->start_tbody();
        my @url = (ASSIGNMENTS, $r->assignment->name, USERS, $r->user->name,
                   START_DATE(), $r->date, END_DATE(), $r->date);
        my @file_rows = @{$r->files} ?
          map {[href(form_url(@url,DO_DOWNLOAD(),1,FILE,$_->name), $_->name),
                $_->size] } @{$r->files} : ["(No files)", ""];
        say multirow([$r->assignment->name, $r->assignment->title,
                      $r->user->name, $r->user->full_name,
                      ($r->date ?
                       (href(form_url(@url, VALIDATION(), 1, DO_RESULTS(), 1),
                             pretty_date($r->date)) .
                        (($r->assignment ne "" and
                          $r->date gt $r->assignment->due) ? " (Late)" : ""))
                       : ("(Nothing submitted)"))], @file_rows);

        if (validation() and $r->date) {
          if (not @{$r->assignment->validators}) {
            say '<tr><td></td>';
            say '<td colspan=7 style="background:rgb(95%,95%,95%);">';
            say "Submission received on @{[pretty_date($r->date)]}.";
            say '</td></tr>';
          } else {
            $ENV{'TIRO_SUBMISSION'} = filename(
              $r->assignment->name, $r->user->name, $r->date);
            $ENV{'TIRO_ASSIGNMENT'} = catfile(
              $config->assignments_dir, $r->assignment->path);
            for my $validator (@{$r->assignment->validators}) {
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
          my $assignment = parse_assignment_file(
            catfile($config->assignments_dir, $path));

          $assignment->dates([map {[list_dates($name, $_->name, 1)]}
                              @all_users]);
          $assignment->name($name);
          $assignment->path($path);
          $assignment;
        }
  } dir_list($config->assignments_dir);
}

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
