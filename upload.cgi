#! /usr/bin/perl -T
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout
umask 0077; # Default to private files

# Modules from Core
use CGI qw/-private_tempfiles -nosticky/;
use Class::Struct;
use File::Copy; # copy() but move() has tainting issues
use File::Path qw/mkpath/;
use DirHandle;
sub say { print @_, "\n"; } # Emulate Perl 5.10 feature

# Modules not from Core
use JSON;
use Date::Manip;
use File::Slurp qw(slurp); # Perl 6 feature
use List::MoreUtils ':all';

################
# Static Definitions
################

# File Paths
use constant DIR => "/u-/adamsmd/projects/upload/demo"; # Root of all paths
use constant GLOBAL_CONFIG_FILE => "global_config.json";

# Structs
struct GlobalConfig=>{title=>'$', folder_configs=>'$', folder_files=>'$',
                      path=>'$', post_max=>'$', admins=>'*@', users=>'*%'};
struct UserConfig=>{name => '$', full_name => '$', expires => '$'};
struct FolderConfig=>{name=>'$', num_submitted =>'$',title=>'$', text=>'$',
                      due=>'$', file_count=>'$', checkers=>'@'};
struct Row=>{folder=>'FolderConfig', user=>'UserConfig', date=>'$', files=>'@'};
struct FileInfo=>{name=>'$', size=>'$'};

################
# Bootstrap
################

my $global_config = GlobalConfig->new(read_config(GLOBAL_CONFIG_FILE));
$CGI::POST_MAX = $global_config->post_max;
($ENV{PATH}) = $global_config->path;
my $q = CGI->new;
die $q->cgi_error() if $q->cgi_error();

################
# Parse Inputs
################

# Input formats
sub trusted ($) { ($_[0] =~ /^(.*)$/s)[0]; }
sub date ($) { ((UnixDate($_[0], "%O") or "") =~ /^([A-Za-z0-9:-]+)$/)[0]; }
sub file ($) { (($_[0] or "") =~ qr/^(?:.*\/)?([A-Za-z0-9_\. -]+)$/)[0]; }
sub bool ($) { $_[0] ? 1 : 0; }

sub param (%) {
    my (%hash) = @_;
    for (keys %hash) {
        eval "sub $_ () { '@{[$hash{$_}->($q->param($_))]}' }";
        eval "sub @{[uc $_]} () { '$_' }";
    }
}

# Basic Inputs
my $now = date "now";
param(start_date => \&date, end_date => \&date);
param(do_search => \&bool, do_download => \&bool,
      do_upload => \&bool, do_results => \&bool);
param(only_latest => \&bool, do_checks => \&bool);
param(submitted_yes => \&bool, submitted_no => \&bool);
param(due_past => \&bool, due_future => \&bool);
param(sort_by => \&file);
use constant { SORT_FOLDER=>'folder', SORT_USER=>'user', SORT_DATE=>'date' };

# Complex Inputs
my $folder_configs = file $global_config->folder_configs;
my $folder_files = file $global_config->folder_files;

use constant {USERS => "users", FOLDERS => "folders",  FILE => 'file' };
my $remote_user = file $q->remote_user();
$remote_user="user1"; # HACK
my $is_admin = any { $_ eq $remote_user } @{$global_config->admins};

my @all_users = $is_admin ? sort keys %{$global_config->users} : ($remote_user);
my @users = $q->param(USERS) ? $q->param(USERS) : @all_users;
@users = sort (intersect(\@all_users, [map { file $_ } @users]));

my $file = file $q->param(FILE);
my @files = $q->upload(FILE);

my @all_folders = dir_list($global_config->folder_configs);
my @folders = map { file $_ } $q->param(FOLDERS);
@folders = sort (intersect(\@all_folders, \@folders));
@folders = map { $_->name }
    grep { due_past() and $_->due le $now or due_future() and $_->due gt $now}
    list_folders(@folders);

# Other inputs
#  - the file being uploaded
#  dir_list: list_dates list_files
#  config:
#   Printing only:
#    GLOBAL_TITLE
#    FOLDER_NAME FOLDER_TITLE FOLDER_TEXT
#    USER_FULL_NAME
#   Processed:
#    GLOBAL_USERS (@all_users)
#    FOLDER_CHECKERS (check_folder as a system command)
#    FOLDER_DUE (folder_results to flag code)
#    FOLDER_FILE_COUNT (folder_results as a loop bound)

################
# Main Code
################

error("No such user: $remote_user")
    unless exists $global_config->users->{$remote_user};
error("Access for $remote_user expired as of ", user($remote_user)->expires)
    unless $now lt date(user($remote_user)->expires);

if (do_download()) { download(); }
elsif (do_upload()) { upload(); }
else {
    render([list_folders(@all_folders)], [list_folders(@folders)],
           [search_results()]); # NOTE: search_results does the non-render work
}
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
    my ($folder, $user) = ($folders[0], $users[0]);
    my $path = filename($folder,$user,start_date(),$file);
    $folder and $user and start_date() and $file and -f $path and -r $path or
        error("Can't read '$folder,$user,@{[start_date()]},$file'");
    print $q->header(-type=>'application/octet-stream',
                     -attachment=>$file, -Content_length=>-s $path);
    copy($path, *STDOUT) or die $!;
}

sub upload {
    @files or error("No files selected for upload.");
    @files == uniq map { file $_ } @files or error("Duplicate file names.");
    my $folder = $folders[0] or error("No folder selected for upload.");

    my $target_dir = filename($folder,$remote_user,$now);
    mkpath($target_dir) or error("Can't create: $folder,$remote_user,$now: $!");
    foreach my $file (@files) {
        my $name = file $file;
        copy($file, "$target_dir/$name") or
            error("Can't save $name in $folder for $remote_user at $now: $!");
    }
    print $q->redirect(-status=>303, # HTTP_SEE_OTHER
                       -uri=>form_url(DO_RESULTS(), 1, DO_CHECKS(), do_checks(),
                                      FOLDERS, $folder, USERS, $remote_user,
                                      START_DATE(), $now, END_DATE(), $now));
}

sub search_results {
    my @rows;
    foreach my $folder (list_folders(@folders)) {
        foreach my $user (list_users($folder->name)) {
            my @dates = list_dates($folder->name, $user->name);
            push @rows, Row->new(folder=>$folder, user=>$user, date=>'',
                                 files=>[]) if submitted_no() and not @dates;
            foreach my $date (@dates) {
                push @rows, Row->new(
                    folder=>$folder, user=>$user, date=>$date,
                    files=>[list_files($folder, $user, $date)])
                    if (submitted_yes());
            }
        }
    }

    return sort {(sort_by() eq SORT_USER and $a->user->name cmp $b->user->name)
                     or (sort_by() eq SORT_DATE and $a->date cmp $b->date)
                     or ($a->folder->name cmp $b->folder->name)
                     or ($a->user->name cmp $b->user->name)
                     or ($a->date cmp $b->date) } @rows;
}

################
# Rendering
################

sub render {
    my ($all_folders, $folders, $rows) = @_;

    print $q->header();
    say $q->start_html(-title=>$global_config->title,
                       -style=>{-verbatim=><<'EOT'});
th { vertical-align:top; text-align:left; }
td { vertical-align:top; }
h2 { border-bottom:2px solid black; }
.navbar { padding:0.3em; width:20em;float:left;border:solid black 1px; }
.navbar > h3:first-child { margin-top:0; } /* Stop spurious margin */
.search TR td * { width:100%; }
.results { width:100%;border-collapse: collapse; }
.results thead { border-bottom:2px solid black; }
.results tbody { border-bottom:1px solid black; }
.results tbody TR:first-child td+td+td+td+td+td+td+td { text-align:right; }
.results tbody TR+TR td+td { text-align:right; }
.results tbody TR+TR td+td[colspan] { text-align:left; }
.results tbody TR td[colspan="1"]+td { background:#EEE; }
.folder { width:100%; border-bottom:1px solid black; }
.body { margin-left:22em; }
EOT

    say $q->h1($global_config->title);

    say $q->start_div({-class=>'navbar'});

    ## Browse folders
    say $q->h3("Select Folder");
    say $q->start_table();
    foreach my $folder (@$all_folders) {
        say row(0, 2, href(form_url(DO_RESULTS(), 1, FOLDERS, $folder->name),
                           $folder->name . ":", $folder->title));
        my $num_submitted = $folder->num_submitted;
        my $num_users = @all_users;
        say row(0, 1, $q->small("&nbsp;&nbsp;Due " . $folder->due),
                $q->small($num_submitted ?
                          (" - Submitted" .
                           ($is_admin ? " ($num_submitted/$num_users)" : "")) :
                          ($now ge $folder->due ? " - Overdue" : "")));
    }
    say $q->end_table();

    say $q->h3("... or", href(form_url(DO_SEARCH(), 1), "Search"));
    ## Search folders
    if (do_search()) {
        say $q->start_form(-action=>'#', -method=>'GET');
        say $q->start_table({-class=>'search'});
        map { say row(0, 1, @$_) } (
            ["User:", multilist(USERS, @all_users)],
            ["Folder:", multilist(FOLDERS, @all_folders)],
            ["Start date: ", $q->textfield(-name=>START_DATE(), -value=>'Any')],
            ["End date: ", $q->textfield(-name=>END_DATE(), -value=>'Any')],
            ["Only latest:", $q->checkbox(-name=>ONLY_LATEST(), -label=>'')],
            ["Run checks:", $q->checkbox(-name=>DO_CHECKS(), -label=>'')],
            ["Status:", boxes(SUBMITTED_YES(), 'Has been Submitted',
                              SUBMITTED_NO(), 'Hasn\'t been Submitted')],
            ["Due:", boxes(DUE_PAST(), 'Due in the Past',
                           DUE_FUTURE(), 'Due in the Future')],
            ["Sort by: ",
             scalar($q->radio_group(
                        -name=>SORT_BY(), -default=>[SORT_FOLDER],
                        -values=>[SORT_FOLDER, SORT_USER, SORT_DATE],
                        -labels=>{SORT_FOLDER, "Folder",
                                  SORT_USER, "User",
                                  SORT_DATE, "Date"}))],
            ["", $q->submit(-value=>"Search")]);
        say $q->end_table();
        say $q->hidden(-name=>DO_SEARCH(), -default=>1);
        say $q->hidden(-name=>DO_RESULTS(), -default=>1);
        say $q->end_form();
    }
    say $q->end_div();

    if (do_results()) {
        say $q->start_div({-class=>'body'});
        say $q->h2("Upload new files");

        my @no_results = ('No results to display.',
                          'Browse or search to select folders.');
        say $q->center(@no_results) unless @$folders;
        foreach my $folder (@$folders) {
            say $q->start_div({-class=>'folder'});
            say $q->h3($folder->title,"(".$folder->name.") - due",$folder->due);
            say $q->div($folder->text);

            say $q->start_form(-method=>'POST', -enctype=>&CGI::MULTIPART,
                               -action=>'#');
            say $q->hidden(-name=>FOLDERS, -value=>$folder->name, -override=>1);
            say $q->hidden(-name=>DO_CHECKS(), -value=>1, -override=>1);
            for my $i (1..$folder->file_count) {
                say $q->p("File $i:", $q->filefield(-name=>FILE, -override=>1));
            }
            say $q->p($q->submit(DO_UPLOAD(), "Upload files"));
            say $q->end_form();
            say $q->end_div();
        }

        say $q->h2("Previously uploaded files");
        say $q->start_table({-class=>'results'});
        say $q->thead($q->Tr($q->th(['Folder','Title','User','Name','Date',
                                     'Check', 'Files','Size (bytes)'])));
        if (not @$rows) { say row(0, 8, $q->center(@no_results)); }
        else {
            foreach my $row (@$rows) {
                say $q->start_tbody();
                my @url = (FOLDERS, $row->folder->name, USERS, $row->user->name,
                           START_DATE(), $row->date, END_DATE(), $row->date);
                my @file_rows = @{$row->files} ?
                    map { [href(form_url(@url, DO_DOWNLOAD(), 1, FILE, $_->name),
                                $_->name),
                           $_->size] } @{$row->files} : ["(No files)", ""];
                my $check = form_url(@url, DO_CHECKS(), 1, DO_RESULTS(), 1);
                say multirow([$row->folder->name, $row->folder->title,
                              $row->user->name, $row->user->full_name,
                              ($row->date ?
                               ($row->date, href($check, "[check]")) :
                               ("(No uploads)", ""))], @file_rows);

                if (do_checks() and $row->date) {
                    my @checkers = @{$row->folder->checkers};
                    my $len = @checkers;
                    my @indexes = (1..$len);
                    my $passed = true {$_ == 0} pairwise
                    { say row(1, 7, "Running @{[$b->[0]]} (check $a of $len)");
                      say $q->start_Tr(), $q->td({-colspan=>2}, "");
                      say $q->start_td({-colspan=>6}), $q->start_div();
                      system @{$b->[1]}, filename(
                          $row->folder->name, $row->user->name, $row->date);
                      die $! if $? == -1;
                      say $q->end_div(), $q->end_td(), $q->end_Tr();
                      say row(2, 6, $? ? 'Failed' : 'Passed');
                      $? } @indexes, @checkers;
                    say row(1, 7, "Passed $passed of $len checks");
                }
                say $q->end_tbody();
            }
        }
        say $q->end_table();
        say $q->end_div();
    }
    say $q->end_html();
}

################
# Listings
################

sub list_files {
    my ($folder, $user, $date) = @_;
    map { FileInfo->new(
              name => $_,
              size => -s filename($folder->name,$user->name,$date,$_)) }
    dir_list($folder_files, $folder->name, $user->name, $date);
}
sub folder {
    FolderConfig->new(
        name => $_[0], read_config($folder_configs, $_[0]),
        num_submitted => true {list_dates($_[0], $_)} @all_users);
}
sub list_folders { map { folder $_ } @_; }
sub user { UserConfig->new(name => $_[0], %{$global_config->users->{$_[0]}}) }
sub list_users { map { user $_ } @users; }
sub list_dates {
    my ($folder, $user) = @_;
    my @dates = dir_list($folder_files, $folder, $user);
    @dates = map { date $_ } @dates;
    @dates = grep { -d filename($folder, $user, $_) } @dates;
    @dates = grep {start_date() le $_} @dates if start_date();
    @dates = grep {end_date() ge $_} @dates if end_date();
    @dates = ($dates[$#dates]) if $#dates != -1 and only_latest();    
    return @dates;
}
sub filename { join('/', DIR, $folder_files, @_); }

################
# HTML Utils
################

sub form_url { my %args = @_; "?" . join "&", map {"$_=$args{$_}"} keys %args }
sub href { my ($href, @rest) = @_; $q->a({-href=>$href}, @rest); }
sub multilist { $q->scrolling_list(
                    -name=>$_[0], -multiple=>1, -size=>3,
                    -values=>[@_[1..$#_]], -default=>[@_[1..$#_]]); }
sub boxes { my %args = @_;
            join $q->br(),
            map { $q->checkbox(-name=>$_,-checked=>1,-label=>$args{$_}) }
            keys %args }
sub row { my ($pre, $span, @data) = @_;
          $q->Tr(($pre ? $q->td({-colspan=>$pre}) : ()),
                 $q->td({-colspan=>$span}, [@data])) }
sub multirow {
    my ($prefix, @rows) = @_;
    "<tr>" . $q->td({-rowspan=>scalar(@rows)}, $prefix) .
        join("</tr><tr>", (map { $q->td($_) } @rows)) . "</tr>";
}

################
# General Utils
################

sub read_config { %{decode_json(trusted slurp(join('/', DIR, @_)))}; }

sub intersect {
    my ($a, $b) = @_; my %a = map {($_,1)} @$a; return grep {$a{$_}} @$b;
}

sub dir_list {
    my $d = DirHandle->new(join '/', DIR, @_);
    my @ds = $d ? $d->read : ();
    $d->close if $d;
    @ds = grep {!/^\./} @ds; # skip dot files
    @ds = grep {!/~$/} @ds; # skip backup files
    return sort @ds;
}
