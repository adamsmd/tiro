#! /usr/bin/perl -T
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout

# Modules from Core
use CGI qw/-private_tempfiles/;
use Class::Struct;
use File::Copy; # copy() and move()
use File::Path qw/mkpath/;
use DirHandle;
use Memoize; memoize('read_config');

# Modules not from Core
use JSON;
use Date::Manip;

# Done:
#  - move search form to left column
#  - Scroll list for search form to select "submitted" or "unsubmitted"
#  - which students haven't submitted

# Future features:
#  - select subset of checkers to run
#  - groups
#  - detailed sort-by
#  - print "all checks passed" and "upload completed"
#  - include timestamp in "upload completed"
#  - file_name regex
#  - assert $config->{$FOLER_NAME} == $folder_name
#  - check configs are valid
#  - highlight incomplete submissions
#  - Admin interface (but be clear what it looks like to student)
#  - hilight overdue
#  - zebra stripes (one in three)
#  - Upload chmod?
#  - error handling
#  - HTML formatting / CSS classes
#  - Separate upload page (so full assignment can be listed)
#  - Checkmark for submitted and meta data on browse, e.g.:
#    - "n/m" submitted, "(past due)", etc.
#  - Download tar-ball.
#  - Use path_info() to dispatch upload, download and pre-upload(?)
#  - Full URL to cgi.cs.indiana.edu? url()
#  - When no folders specified use different text for result pane
#  - Server error on upload with no file

# config file validator
# HTML container for validator output


# NOTE: uploading multiple file w/ same name clobbers older files

# File Paths
use constant DIR => "/u-/adamsmd/projects/upload/demo";
#use constant DIR => "demo";
use constant GLOBAL_CONFIG_FILE => "global_config.json";

# CGI Constants
use constant { ACTION_DOWNLOAD_FILE => "download_file",
               ACTION_UPLOAD_FILES => "upload_files",
               ACTION_CHECK_FOLDER => "check_folder" };
use constant { USERS => "users", FOLDERS => "folders",
               START_DATE => "start_date", END_DATE => "end_date",
               ONLY_MOST_RECENT => "only_most_recent" };
use constant HEADER_OCTET_STREAM => 'application/octet-stream';
use constant HTTP_SEE_OTHER => 303;
use constant FILE => 'file';
use constant { DUE => 'due', DUE_PAST => 'past', DUE_FUTURE => 'future' };
use constant { SUBMITTED => 'submitted', SUBMITTED_YES => 'yes', SUBMITTED_NO => 'no' };
use constant { SORTING => 'sorting', SORTING_FOLDER => 'sorting_folder',
               SORTING_USER => 'sorting_user', SORTING_DATE => 'sorting_date' };

# Other constants
use constant DATE_FORMAT => "%O"; # TODO: Put in global config?
use constant FILE_RE => qr/^(?:.*\/)?([A-Za-z0-9_\. -]+)$/;
use constant TRUSTED_RE => qr/^(.*)$/s;
use constant DATE_RE => qr/^([A-Za-z0-9:-]+)$/;

# Structs
struct(GlobalConfig=>[title=>'$', folder_configs=>'$', folder_files=>'$',
                      cgi_url=>'$', path=>'$', # Path for checkers
                      post_max=>'$', admins=>'*@', users=>'*%' ]);
struct(UserConfig=>[ name => '$', full_name => '$']);
struct(FolderConfig=>[name=>'$', title=>'$', text=>'$', due=>'$',
                      file_count=>'$', checkers=>'@']);
struct(Row=>[
           folder=>'FolderConfig', user=>'UserConfig', date=>'$', files=>'@']);
struct(File=>[name=>'$', size=>'$']);

################
# Setup
################

my $q = CGI->new;

my $error = $q->cgi_error(); # TODO
if ($error) { error($error); }

my $global_config = GlobalConfig->new(read_config(GLOBAL_CONFIG_FILE));
$CGI::POST_MAX = $global_config->post_max;
($ENV{PATH}) = $global_config->path;

################
# Inputs
################

# Dates
my ($start_date) = (UnixDate($q->param(START_DATE), DATE_FORMAT) or "") =~ DATE_RE;
my ($end_date) = (UnixDate($q->param(END_DATE), DATE_FORMAT) or "") =~ DATE_RE;
my ($now) = (UnixDate("now", DATE_FORMAT) or "") =~ DATE_RE;

# Flags
my $only_most_recent = $q->param(ONLY_MOST_RECENT) ? 1 : 0;
my $submitted_yes = (grep { $_ eq SUBMITTED_YES } $q->param(SUBMITTED)) ? 1 : 0;
my $submitted_no = (grep { $_ eq SUBMITTED_NO } $q->param(SUBMITTED)) ? 1 : 0;
my $due_past = (grep { $_ eq DUE_PAST } $q->param(DUE)) ? 1 : 0;
my $due_future = (grep { $_ eq DUE_FUTURE } $q->param(DUE)) ? 1 : 0;
my ($sorting) = ($q->param(SORTING) or "") =~ /^([A-Za-z0-9_]*)$/;

# Directories
my ($folder_configs) = $global_config->folder_configs =~ FILE_RE;
my ($folder_files) = $global_config->folder_files =~ FILE_RE;

# User
my ($remote_user) = ($q->remote_user() or "") =~ FILE_RE;
$remote_user="user1";
my $is_admin = grep { $_ eq $remote_user } @{$global_config->admins};
my @all_users = sort keys %{$global_config->users};
@all_users = sort (intersect(\@all_users, [$remote_user])) unless $is_admin;
my @users = sort map { $_ =~ FILE_RE } $q->param(USERS);
@users = sort (intersect(\@all_users, \@users));

# Download file
my ($file) = ($q->param(FILE) or "") =~ FILE_RE;

# Folders
my @all_folders = dir_list($global_config->folder_configs);
my @folders = map { $_ =~ FILE_RE } $q->param(FOLDERS);
@folders = sort (intersect(\@all_folders, \@folders));
@folders = map { $_->name }
           grep { $due_past and $_->due le $now or
                  $due_future and $_->due gt $now} list_folders(@folders);

# Other inputs
#  param: $ACTION_*
#  upload: $UPLOAD_FILE
#  dir_list: list_dates list_files
#  config:
#   Printing only:
#    GLOBAL_TITLE GLOBAL_CGI_URL
#    FOLDER_NAME FOLDER_TITLE FOLDER_TEXT
#    USER_FULL_NAME
#   Processed:
#    GLOBAL_USERS (@all_users)
#    FOLDER_CHECKERS (check_folder as a system command)
#    FOLDER_DUE (folder_results to flag code)
#    FOLDER_FILE_COUNT (folder_results as a loop bound)

################
# Do work
################

if ($q->param(ACTION_DOWNLOAD_FILE)) { download(); }
elsif ($q->param(ACTION_UPLOAD_FILES)) { upload(); }
else {
    print $q->header();
    print $q->start_html(-title=>$global_config->title), "\n";
    print $q->start_div();
    print $q->start_div({-style=>'width:20em;float:left;'});
    browse_folders();
    search_form();
    print $q->end_div();
    print $q->start_div({-style=>'margin-left:20em'});
    if ($q->param(ACTION_CHECK_FOLDER)) { check_folder(); print $q->hr(); }
    search_results(); print $q->hr();
    folder_results();
    print $q->end_div();
    print $q->end_div();
    print $q->end_span();
    print $q->end_html(), "\n";
}
exit 0;

################################
# Actions
################################

sub download {
    my $folder = $folders[0] or die;
    my $user = $users[0] or die;
    my $filename = join('/',DIR,$folder_files,$folder,$user,$start_date,$file);
    print $q->header(-type=>HEADER_OCTET_STREAM,
                     -attachment=>$file, -Content_length=>-s $filename);
    copy($filename, *STDOUT) or die; # TODO: error message
}

sub upload {
    my $folder = $folders[0] or die; # TODO
    my $target_dir = join('/', DIR, $folder_files,$folder,$remote_user,$now);

    mkpath($target_dir) or die; # TODO: error message (sleep 1)
    foreach my $file ($q->upload(FILE)) {
        die if not $file; # TODO: error message
        my ($name) = $file =~ FILE_RE;
        move($file, "$target_dir/$name"); # TODO die and error message
    }
    print $q->redirect(
        -uri=>form_url(ACTION_CHECK_FOLDER, $q->param(ACTION_CHECK_FOLDER),
                       FOLDERS, $folder, USERS, $remote_user,
                       START_DATE, $now, END_DATE, $now),
        -status=>HTTP_SEE_OTHER);
}

sub browse_folders {
    # Print
    print $q->h3("Browse"), "\n";
    print $q->start_ul(), "\n";
    foreach my $folder (list_folders(@all_folders)) {
        print $q->li($q->a({-href=>form_url(FOLDERS, $folder->name,
                                            map { (USERS, $_) } @all_users)},
                           $folder->name . ":", $folder->title,
                           " (due " . $folder->due . ")")), "\n";
    }
    print $q->end_ul(), "\n";
}

sub search_form {
    # Print
    print $q->h3("Search"), "\n";
    print $q->start_form(-action=>$global_config->cgi_url);
    print $q->start_table();
    print $q->start_Tr(), "\n";
    print $q->Tr($q->td(["User:", $q->scrolling_list(
                      -name=>USERS, -values=>\@all_users,
                      -default=>\@all_users, -multiple=>1, -size=>3)])), "\n";
    print $q->Tr($q->td(["Folder:", $q->scrolling_list(
                     -name=>FOLDERS, -values=>\@all_folders,
                     -default=>\@all_folders, -multiple=>1, -size=>3)])), "\n";
    print $q->Tr($q->td(["Date start: ", $q->textfield(-name=>START_DATE, -size=>10)])), "\n";
    print $q->Tr($q->td(["Date end: ", $q->textfield(-name=>END_DATE, -size=>10)])), "\n";
    print $q->Tr($q->td(["Only latest:", $q->checkbox(-name=>ONLY_MOST_RECENT, -label=>'')])), "\n";
    print $q->Tr($q->td(["Status:", $q->scrolling_list(
        -name=>SUBMITTED, -values=>[SUBMITTED_YES, SUBMITTED_NO], -multiple=>1, -default=>[SUBMITTED_YES, SUBMITTED_NO],
        -labels=>{SUBMITTED_YES() => "Submitted",
                  SUBMITTED_NO() => "Not Submitted"})])), "\n";
    print $q->Tr($q->td(["Due:", $q->scrolling_list(
        -name=>DUE, -values=>[DUE_PAST, DUE_FUTURE], -multiple=>1, -default=>[DUE_PAST, DUE_FUTURE],
        -labels=>{DUE_PAST() => "Past",
                  DUE_FUTURE() => "Future"})])), "\n";
    print $q->Tr($q->td(["Sort by: ", $q->scrolling_list(
        -name=>SORTING, -values=>[SORTING_FOLDER, SORTING_USER, SORTING_DATE],
        -labels=>{SORTING_FOLDER() => "Folder",
                  SORTING_USER() => "User",
                  SORTING_DATE() => "Date"})])), "\n";

    print $q->Tr($q->td(["",$q->submit(-value=>"Search")])), "\n";
    print $q->end_table();
    print $q->end_form();
}

sub check_folder {
    foreach my $folder (list_folders(@folders)) {
        foreach my $user (list_users($folder->name)) {
            foreach my $date (list_dates($folder->name, $user->name)) {
                print $q->h2("Checking", $folder->name, "for", $user->name,
                             "on", $date), "\n";
                foreach my $checker (@{$folder->checkers}) {
                    system @$checker, join(
                        '/', DIR, $folder_files, $folder->name,
                        $user->name, $date); # TODO: die and error message
                }
            }
        }
    }
}

sub search_results {
    # Search
    my @rows;
    foreach my $folder (list_folders(@folders)) {
        foreach my $user (list_users($folder->name)) {
            my @dates = list_dates($folder->name, $user->name);
            if (@dates) {
                if ($submitted_yes) {
                    foreach my $date (@dates) { # TODO: or none exist
                        push @rows, Row->new(
                            folder=>$folder, user=>$user, date=>$date,
                            files=>[list_files($folder->name, $user->name, $date)]);
                    }
                }
            } else {
                if ($submitted_no) {
                    push @rows, Row->new(folder=>$folder, user=>$user, date=>'', files=>[]);
                }
            }
        }
    }

    # Print
    print $q->h3("Uploaded Files"), "\n";
    print $q->start_table({-border=>2}), "\n";
    print $q->thead(
        $q->Tr($q->th(["Folder", "Title", "User", "Name",
                       "Date", "Check", "File", "Size (bytes)"]))), "\n";
    foreach my $row (sort {($sorting eq SORTING_USER and
                            $a->user->name cmp $b->user->name) or
                            ($sorting eq SORTING_DATE and
                             $a->date cmp $b->date) or
                             ($a->folder->name cmp $b->folder->name) or
                             ($a->user->name cmp $b->user->name) or
                             ($a->date cmp $b->date)} @rows) {
        print $q->start_Tr(), "\n";
        print $q->td([
            $row->folder->name, $row->folder->title, $row->user->name,
            $row->user->full_name, $row->date,
            $row->date ? $q->a({-href=>form_url(
                        ACTION_CHECK_FOLDER, 1, FOLDERS, $row->folder->name,
                        USERS, $row->user->name, START_DATE, $row->date,
                        END_DATE, $row->date)}, "[check]") : '']), "\n";

        my $first = 1;
        foreach my $file (sort @{$row->files}) {
            print $q->end_Tr(), $q->start_Tr(), $q->td({colspan=>6}), "\n"
                unless $first;
            $first = 0;

            print $q->td(
                $q->a({-href=>form_url(
                            ACTION_DOWNLOAD_FILE,1, FOLDERS, $row->folder->name,
                            USERS, $row->user->name, START_DATE, $row->date, 
                            END_DATE, $row->date, FILE, $file->name)},
                      $file->name));

            print $q->td({-align=>'right'}, $file->size);
        }
        print $q->end_Tr(), "\n";
    }

    print $q->end_table(), "\n";
}

sub folder_results {
    # Search
    my @folders = list_folders(@folders);

    # Print
    print $q->h3("Uploads for $remote_user");
    print $q->start_table({-border=>2}), "\n";
    foreach my $folder (@folders) {
        print list_dates($folder, $remote_user), "\n";
        if (filter_submitted($folder, $remote_user)) {
        print $q->h3($folder->name . ":", $folder->title,
                     " (due " . $folder->due . ")"), "\n";
        print $q->div($folder->text), "\n";

        print $q->start_form(-method=>'POST', -action=>$global_config->cgi_url,
                             -enctype=>&CGI::MULTIPART);
        print $q->hidden(
            -name=>FOLDERS, -value=>$folder->name, -override=>1), "\n";
        for (my $i = 0; $i < $folder->file_count; $i++) {
            print $q->p("File", $i+1 . ":",
                        $q->filefield(-name=>FILE, -override=>1)), "\n";
        }
        print $q->p($q->checkbox(-name=>ACTION_CHECK_FOLDER,
                                 -checked=>1, -override=>1,
                                 -label=>"Check after upload")), "\n";
        print $q->submit(ACTION_UPLOAD_FILES, "Upload files"), "\n";
        print $q->end_form(), "\n";
        }
    }
    print $q->end_table(), "\n";
}

################
# Listings
################

sub filter_submitted {
    my ($folder, $user) = @_;
    return list_dates($folder->name, $user) ? $submitted_yes : $submitted_no;
}

sub list_folders {
    map { FolderConfig->new(name => $_, read_config($folder_configs, $_)) } @_;
}

sub list_users {
    map { UserConfig->new(name => $_, %{$global_config->users->{$_}}) } @users;
}

sub list_dates {
    my ($folder, $user) = @_;
    my $dir = join('/', $folder_files, $folder, $user);
    my @dates = dir_list($dir);
    @dates = map { $_ =~ DATE_RE } @dates;
    @dates = grep { -d (DIR . "/$dir/$_") } @dates;
    @dates = grep {$start_date le $_} @dates if $start_date;
    @dates = grep {$end_date ge $_} @dates if $end_date;
    @dates = ($dates[$#dates]) if $#dates != -1 and $only_most_recent;    
    return @dates;
}

sub list_files {
    my ($folder, $user, $date) = @_;
    my $dir = join('/', $folder_files, $folder, $user, $date);
    map { File->new(name => $_, size => -s DIR . "/$dir/$_") } dir_list($dir);
}

################
# CGI Utility
################

# Expects: ($key1, $val1, $key2, $val2)
# Returns: $cgi_url?$key1&$val1&$key2&val2
sub form_url {
    my $str = $global_config->cgi_url;
    for (my $i = 0; $i <= $#_; $i+=2) {
        $str .= ($i == 0 ? "?" : "&") . $_[$i] . "=" . $_[$i+1];
    }
    return $str;
}

################
# General Util
################

sub read_config {
    my $filename = join '/', DIR, @_;
    local $/;
    open(my $fh, '<', $filename) or die "No file $filename\n"; # TODO: error msg
    my $obj = decode_json(<$fh> =~ TRUSTED_RE);
    return %$obj;
}

sub intersect {
    my ($a, $b) = @_;
    my %a = map {($_,1)} @$a;
    return grep {$a{$_}} @$b;
}

sub dir_list {
    my $dir = join '/', DIR, @_;

    # TODO: die on error and error message
    my $d = DirHandle->new($dir);
    my @ds = $d ? $d->read : ();
    $d->close if $d;
    @ds = grep {!/^\./} @ds; # skip dot files
    @ds = grep {!/~$/} @ds; # skip backup files
    return sort @ds;
}
