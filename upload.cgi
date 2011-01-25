#! /usr/bin/perl -T
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout
umask 0177; # Default to private files

# Configuration
my %global_config_hash = (
#    global_config_file=>"/l/cgi/rpjames/cgi-pub/global_config.json",
#    working_dir=>"/l/cgi/rpjames/cgi-pub/",
    global_config_file=>"/u-/adamsmd/projects/upload/demo/global_config.json",
    working_dir=>"/u-/adamsmd/projects/upload/demo"
    );

# Modules from Core
use CGI qw/-private_tempfiles -nosticky/;
use Class::Struct;
use File::Copy; # copy() but move() has tainting issues
use File::Path qw/mkpath/;
use File::Spec::Functions;
use Time::HiRes qw/time/;
sub say { print @_, "\n"; } # Emulate Perl 6 feature

# Modules not from Core
use JSON;
use Date::Manip;
use File::Slurp qw(slurp); # Perl 6 feature
use List::MoreUtils ':all';

################
# Static Defs
################

# Structs
struct GlobalConfig=>{title=>'$', admins=>'*@', assignment_configs=>'$',
                      assignment_files=>'$', assignment_regex=>'$', path=>'$',
                      post_max=>'$', date_format=>'$', users=>'*%', working_dir=>'$'};
struct UserConfig=>{name => '$', full_name => '$', expires => '$'};
struct AssignmentConfig=>{
    name=>'$', num_done =>'$',title=>'$', text=>'$',
    text_file=>'$', due=>'$', file_count=>'$', tests=>'@'};
struct Row=>{
    assignment=>'AssignmentConfig', user=>'UserConfig', date=>'$', files=>'@'};
struct FileInfo=>{name=>'$', size=>'$'};

#Global
#title
#assignment_configs
#assignment_files
#assignment_regex
#path
#post_max
#admins
#
#Users:
#name full_name expires
#
#Assignment:
#name, title, text, due, file_count, tests

################
# Bootstrap
################

my $start_time = time();
my $global_config = GlobalConfig->new(
    %global_config_hash, exists $global_config_hash{'global_config_file'} ?
    slurp_json($global_config_hash{'global_config_file'}) : ());
chdir $global_config->working_dir or error("$!");
$CGI::POST_MAX = $global_config->post_max;
$ENV{PATH} = $global_config->path;
my $q = CGI->new;
die $q->cgi_error() if $q->cgi_error();

################
# Parse Inputs
################

# Input formats
sub date { ((UnixDate($_[0], "%O") or "") =~ /^([A-Za-z0-9:-]+)$/)[0]; }
sub file { (($_[0] or "") =~ qr/^(?:.*\/)?([A-Za-z0-9_\. -]+)$/)[0]; }
sub keyword { (($_[0] or "") =~ qr/^([A-Za-z0-9]*)/)[0]; }
sub bool { $_[0] ? 1 : 0; }
sub search_bool { (not from_search() or $_[0]) ? 1 : 0; }

# Basic Inputs
my $now = date "now";
define_param(start_date => \&date, end_date => \&date);
define_param(do_search => \&bool, from_search => \&bool, do_download => \&bool,
             do_upload => \&bool, do_upload_form => \&bool, do_results => \&bool);
define_param(only_latest => \&bool, do_tests => \&bool);
define_param(done_yes => \&search_bool, done_no => \&search_bool);
define_param(due_past => \&search_bool, due_future => \&search_bool);
define_param(sort_by => \&keyword);
use constant {SORT_ASSIGNMENT=>'assignment',SORT_USER=>'user',SORT_DATE=>'date'};

# Complex Inputs
my $remote_user = file ($q->remote_user() =~ /^(\w+)\@/);
#$remote_user="user1"; # HACK for demo purposes
my $is_admin = any { $_ eq $remote_user } @{$global_config->admins};

use constant {USERS => "users", ASSIGNMENTS => "assignments",  FILE => 'file' };
my @all_users = $is_admin ? sort keys %{$global_config->users} : ($remote_user);
@all_users = map { user($_) } @all_users;
my @users = $q->param(USERS) ? $q->param(USERS) : map {$_->name} @all_users;
@users = intersect_key(\@all_users, sub {$_[0]->name}, \@users);

my @all_assignments = list_assignments();
my @assignments = map { file $_ } $q->param(ASSIGNMENTS);
@assignments = intersect_key(\@all_assignments,sub {$_[0]->name},\@assignments);
@assignments = grep { due_past() and $_->due le $now or
                  due_future() and $_->due gt $now} @assignments;

my $file = file $q->param(FILE);
my @files = $q->upload(FILE);

################
# Main Code
################

error("No such user: $remote_user")
    unless exists $global_config->users->{$remote_user};
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
    say $q->start_html(-title=>$global_config->title . ": Error");
    say $q->h1($global_config->title . ": Error");
    my ($package, $filename, $line) = caller;
    say $q->p([@_, "(At line $line.)", "Go back and try again."]);
    exit 0;
}

sub download {
    @assignments and @users and start_date() and $file or
        error ("Bad download request\n");
    my ($assignment, $user) = ($assignments[0]->name, $users[0]->name);
    my $path = filename($assignment,$user,start_date(),$file);
    -f $path and -r $path or
        error("Can't read $file in $assignment for $user at @{[start_date()]}");
    print $q->header(-type=>'application/octet-stream',
                     -attachment=>$file, -Content_length=>-s $path);
    copy($path, *STDOUT) or die $!;
}

sub upload {
    @files or error("No files selected for upload.");
    @files == uniq map { file $_ } @files or error("Duplicate file names.");
    my $assignment = $assignments[0] or
        error("No assignment selected for upload.");

    my $target_dir = filename($assignment->name,$remote_user,$now);
    mkpath($target_dir) or
        error("Can't mkdir in @{[$assignment->name]} for " .
              "$remote_user at $now: $!");
    foreach my $file (@files) {
        my $name = file $file;
        copy($file, "$target_dir/$name") or
            error("Can't save $name in @{[$assignment->name]} " .
                  "for $remote_user at $now: $!");
    }
    print $q->redirect(-status=>303, # HTTP_SEE_OTHER
                       -uri=>form_url(DO_RESULTS(), 1, DO_TESTS(), do_tests(),
                                      ASSIGNMENTS, $assignment->name,
                                      USERS, $remote_user,
                                      START_DATE(), $now, END_DATE(), $now));
}

sub search_results {
    my @rows;
    foreach my $assignment (@assignments) {
        foreach my $user (@users) {
            my @dates = list_dates($assignment->name, $user->name);
            push @rows, Row->new(
                assignment=>$assignment, user=>$user, date=>'', files=>[])
                if done_no() and not @dates;
            foreach (@dates) {
                push @rows, Row->new(
                    assignment=>$assignment, user=>$user, date=>$_,
                    files=>[list_files($assignment, $user, $_)]) if done_yes();
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
    say $q->start_html(-title=>$global_config->title,
                       -style=>{-verbatim=><<'EOT'});
th { vertical-align:top; text-align:left; }
td { vertical-align:top; }
h2 { border-bottom:2px solid black; }
.navbar { padding:0.3em; width:19em; float:left; border:solid black 1px; }
.navbar > h3:first-child { margin-top:0; } /* Stop spurious margin */
.search TR td * { width:100%; }
.results { width:100%;border-collapse: collapse; }
.results thead { border-bottom:2px solid black; }
.results tbody { border-bottom:1px solid black; }
.results tbody TR:first-child td+td+td+td+td+td+td+td { text-align:right; }
.results tbody TR+TR td+td { text-align:right; }
.results tbody TR+TR td+td[colspan] { text-align:left; }
.results tbody TR td[colspan="1"]+td { background:#EEE;
}
.assignment { width:100%; border-bottom:1px solid black; margin-bottom:1.3em; }
.body { margin-left:21em; }
.footer { clear:left; text-align:right; font-size: small; }
.welcome { float:right; font-weight:bold; }
EOT

    say $q->div({-class=>'welcome'},
                "Welcome $remote_user<br>Current time is", pretty_date($now));
    say $q->h1($global_config->title);

    say $q->start_div({-class=>'navbar'});

    say $q->h3("Select Assignment");
    say $q->start_table();
    foreach my $assignment (@all_assignments) {
        say row(0, 2, href(form_url(DO_UPLOAD_FORM(), 1, DO_RESULTS(), 1,
                                    ASSIGNMENTS, $assignment->name),
                           $assignment->name . ": ", $assignment->title));
        my $num_done = $assignment->num_done;
        my $num_users = @all_users;
        say row(0, 1,
                $q->small("&nbsp;&nbsp;Due ".pretty_date($assignment->due)),
                $q->small($num_done ?
                          (" - Done" .
                           ($is_admin ? " ($num_done/$num_users)" : "")) :
                          ($now ge $assignment->due ? " - Late" : "")));
    }
    say $q->end_table();

    say $q->h3("... or", href(form_url(DO_SEARCH(), 1), "Search"));
    if (do_search()) {
        say $q->start_form(-action=>'#', -method=>'GET');
        say $q->start_table({-class=>'search'});
        say $q->hidden(-name=>DO_SEARCH(), -default=>1);
        say $q->hidden(-name=>DO_RESULTS(), -default=>1);
        say $q->hidden(-name=>FROM_SEARCH(), -default=>1);
        map { say row(0, 1, @$_) } (
            ["User:", multilist(USERS, map {$_->name} @all_users)],
            ["Assignment:", multilist(ASSIGNMENTS, map {$_->name} @all_assignments)],
            ["Show:",
             boxes(DO_TESTS(), do_tests(), 'Tests',
                   DO_UPLOAD_FORM(), do_upload_form(), 'Upload Form')],
            ["","&nbsp;"],
            ["Start date: ", $q->textfield(-name=>START_DATE(), -value=>'Any')],
            ["End date: ", $q->textfield(-name=>END_DATE(), -value=>'Any')],
            ["Select Only:",
             boxes(ONLY_LATEST(), only_latest(), 'Most Recent and',
                   DONE_YES(), done_yes(), 'Done or',
                   DONE_NO(), done_no(), 'Not Done or',
                   DUE_PAST(), due_past(), 'Due in Past or',
                   DUE_FUTURE(), due_future(), 'Due in Future')],
            ["Sort by: ",
             scalar($q->radio_group(
                        -columns=>1, -name=>SORT_BY(), -default=>[SORT_ASSIGNMENT],
                        -values=>[SORT_ASSIGNMENT, SORT_USER, SORT_DATE],
                        -labels=>{SORT_ASSIGNMENT, "Assignment",
                                  SORT_USER, "User",
                                  SORT_DATE, "Date"}))],
            ["", $q->submit(-value=>"Search")]);
        say $q->end_table();
        say $q->end_form();
    }
    say $q->end_div();

    say $q->start_div({-class=>'body'});
    my @no_results = ('No results to display.',
                      'Browse or search to select assignment.');
    if (do_upload_form()) {
        say $q->center(@no_results) unless @assignments;
        foreach my $assignment (@assignments) {
            say $q->start_div({-class=>'assignment'});
            say $q->h2($assignment->name . ": ", $assignment->title);
            say $q->h4("Due by ", pretty_date($assignment->due));
            say $q->div(scalar(slurp(catfile($global_config->assignment_configs,
                                             $assignment->text_file))))
                if defined $assignment->text_file;
            say $q->div($assignment->text) if defined $assignment->text;

            say $q->start_form(-method=>'POST', -enctype=>&CGI::MULTIPART,
                               -action=>'#');
            say $q->hidden(-name=>ASSIGNMENTS, -value=>$assignment->name,
                           -override=>1);
            say $q->hidden(-name=>DO_TESTS(), -value=>1, -override=>1);
            say $q->p("File $_:", $q->filefield(-name=>FILE, -override=>1))
                for (1..$assignment->file_count);
            say $q->p($q->submit(DO_UPLOAD(), "Upload files"))
                if $assignment->file_count;
            say $q->end_form();
            say $q->end_div();
        }
    }

    if (do_results()) {
        say $q->start_table({-class=>'results'});
        say $q->thead($q->Tr($q->th(["#","Title","User","Name","Date",
                                     "Run<br/>Tests", "Files","Size<br/>(bytes)"])));
        if (not @rows) { say row(0, 8, $q->center(@no_results)); }
        else {
            foreach my $row (@rows) {
                say $q->start_tbody();
                my @url = (ASSIGNMENTS, $row->assignment->name,
                           USERS, $row->user->name,
                           START_DATE(), $row->date, END_DATE(), $row->date);
                my @file_rows = @{$row->files} ?
                    map {[href(form_url(@url, DO_DOWNLOAD(), 1, FILE, $_->name),
                               $_->name),
                          $_->size] } @{$row->files} : ["(No files)", ""];
                my $test = form_url(@url, DO_TESTS(), 1, DO_RESULTS(), 1);
                say multirow([$row->assignment->name, $row->assignment->title,
                              $row->user->name, $row->user->full_name,
                              ($row->date ? (pretty_date($row->date),
                                             href($test, "Run")) :
                               ("(No uploads)", ""))], @file_rows);

                if (do_tests() and $row->date) {
                    my @tests = @{$row->assignment->tests};
                    my $len = @tests;
                    my @indexes = (1..$len);
                    my $passed = true {$_ == 0} pairwise
                    { say row(1, 7, "Running @{[$b->[0]]} (test $a of $len)");
                      say $q->start_Tr(), $q->td({-colspan=>2}, "");
                      say $q->start_td({-colspan=>6}), $q->start_div();
                      system @$b[1..$#$b], filename(
                          $row->assignment->name, $row->user->name, $row->date);
                      die $! if $? == -1;
                      say $q->end_div(), $q->end_td(), $q->end_Tr();
                      say row(2, 6, $? ? 'Failed' : 'Passed');
                      $? } @indexes, @tests;
                    say row(1, 7, @tests ? "Passed $passed of $len tests"
                                         : "(No tests)");
                }
                say $q->end_tbody();
            }
        }
        say $q->end_table();
    }
    say $q->end_div();

    say $q->p({-class=>'footer'}, "Completed in",
              sprintf("%0.3f", time() - $start_time), "seconds.");
    say $q->end_html();
}

################
# Listings
################

sub list_assignments {
    map { my $path = $_;
          my ($name) = /@{[$global_config->assignment_regex]}/;
          $name ? AssignmentConfig->new(
              name=> $name,
              num_done=> (true {list_dates($path, $_->name)} @all_users),
              slurp_json($global_config->assignment_configs, $path)) :
              (); }
    dir_list($global_config->assignment_configs);
}
sub user { UserConfig->new(name => $_[0], %{$global_config->users->{$_[0]}}) }
sub list_dates {
    my ($assignment, $user) = @_;
    my @dates = map { date $_ } dir_list(
        $global_config->assignment_files, $assignment, $user);
    @dates = grep { -d filename($assignment, $user, $_) } @dates;
    @dates = grep {start_date() le $_} @dates if start_date();
    @dates = grep {end_date() ge $_} @dates if end_date();
    @dates = ($dates[$#dates]) if $#dates != -1 and only_latest();    
    return @dates;
}
sub list_files {
    my ($assignment, $user, $date) = @_;
    map {FileInfo->new(name=>$_,
                       size=>-s filename(
                           $assignment->name,$user->name,$date,$_))}
    dir_list($global_config->assignment_files,
             $assignment->name, $user->name, $date);
}
sub filename { catfile($global_config->assignment_files, @_); }

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

sub pretty_date { UnixDate($_[0], $global_config->date_format) }
sub form_url { my %args = @_; "?" . join "&", map {"$_=$args{$_}"} keys %args }
sub href { my ($href, @rest) = @_; $q->a({-href=>$href}, @rest); }
sub multilist { $q->scrolling_list(
                    -name=>$_[0], -multiple=>1, -size=>5,
                    -values=>[@_[1..$#_]], -default=>[@_[1..$#_]]); }
sub boxes { my ($name, $value, $label, @rest) = @_;
            $q->checkbox($name, $value, 'on', $label) .
                (@rest ? $q->br() . boxes(@rest) : ""); }
sub row { my ($pre, $span, @data) = @_;
          $q->Tr(($pre ? $q->td({-colspan=>$pre}) : ()),
                 $q->td({-colspan=>$span}, [@data])) }
sub multirow { my ($prefix, @rows) = @_;
               "<tr>" . $q->td({-rowspan=>scalar(@rows)}, $prefix) .
                   join("</tr><tr>", (map { $q->td($_) } @rows)) . "</tr>"; }

################
# General Utils
################

sub trusted { ($_[0] =~ /^(.*)$/s)[0]; } # Untaint the value
sub slurp_json { %{decode_json(trusted(scalar(slurp(catfile(@_)))))} }
sub intersect { my %a = map {($_,1)} @{$_[0]}; grep {$a{$_}} @{$_[1]} }

sub intersect_key {
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
