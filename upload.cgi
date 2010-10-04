#! /usr/bin/perl -T

use warnings;
use strict;
$|++;

# Modules from Core
use CGI q/-private_tempfiles/;
use File::Copy;
use File::Path;
use DirHandle;
use FileHandle;
use Memoize;

# Modules not from Core
use JSON;
use Date::Manip;

# Future features:
#  - select subset of checkers to run
#  - groups

# TODO: sort by (e.g. full name)
# TODO: print "all checks passed"
# TODO: file_name regex
# TODO: assert $config->{$FOLER_NAME} == $folder_name
# TODO: check configs are valid
# TODO: Must be able to show student interface to admin
#       or make it clear what the student doesn't see
# TODO: Print "upload completed at ..."
# TODO: unselect all
#    window.addEvent('load', function() {
#        new DatePicker('.demo_vista', { pickerClass: 'datepicker_vista' });
# TODO: is overdue
# TODO: zebra stripes
# TODO: Upload chmod?
# TODO: upload and move errors
# TODO: error on checking non-existant folder
# TODO: CSS classes
# TODO: browse on left

# NOTE: uploading multiple file w/ same name clobbers older files

# File Paths
#my $DIR="/u-/adamsmd/projects/upload/tmp";
my $DIR="demo";
my $GLOBAL_CONFIG_FILE="global_config.json";

# CGI Constants
my $ACTION_DOWNLOAD_FILE="download_file";
my $ACTION_UPLOAD_FILES="upload_files";
my $ACTION_FIND_FILES="find_files";
my $ACTION_FIND_FOLDERS="find_folders";
my $ACTION_CHECK_FOLDER="check_folder";

my $USERS="users";
my $GROUPS="groups";
my $FOLDERS="folders";
my $START_DATE="start_date";
my $END_DATE="end_date";
my $ONLY_MOST_RECENT="only_most_recent";

my $HEADER_OCTET_STREAM='application/octet-stream';

# Upload/download constants
my $FOLDER="folder";
my $USER="user";
my $UPLOAD_FILE="upload_file";
my $DOWNLOAD_FILE="download_file";
my $DATE="date";

# Config constants
my $GLOBAL_TITLE = 'title';
my $GLOBAL_FOLDER_CONFIGS = 'folder_configs';
my $GLOBAL_FOLDER_FILES = 'folder_files';
my $GLOBAL_CGI_URL = 'cgi_url';
my $GLOBAL_PATH = 'path'; # Path to search for checkers
my $GLOBAL_POST_MAX = 'post_max';
my $GLOBAL_ADMINS = 'admins';
my $GLOBAL_USERS = 'users';

my $FOLDER_NAME = "name";
my $FOLDER_TITLE = "title";
my $FOLDER_TEXT = "text";
my $FOLDER_DUE = "due";
my $FOLDER_FILE_COUNT = "file_count";
my $FOLDER_CHECKERS = "checkers";

my $USER_NAME = 'user_name';
my $USER_FULL_NAME = 'full_name';

# Other constants
my $DATE_FORMAT = "%O"; # TODO: Put in global config?

memoize('read_config');

################
# Setup
################

my $q = CGI->new;

my $error = $q->cgi_error(); # TODO
if ($error) { error($error); }

my $global_config = read_config($GLOBAL_CONFIG_FILE);
$CGI::POST_MAX = $global_config->{$GLOBAL_POST_MAX};
($ENV{PATH}) = $global_config->{$GLOBAL_PATH} =~ /^(.*)$/;

################
# Inputs
################

# Directories
my ($folder_configs, $folder_files) =
    map { $global_config->{$_} =~ /^([A-Za-z0-9_ ]+)$/ }
        ($GLOBAL_FOLDER_CONFIGS, $GLOBAL_FOLDER_FILES);

# Single folder and user
my ($remote_user, $user, $folder) =
    map { ($_ or "") =~ /^([A-Za-z0-9]+)$/ }
        ($q->remote_user(), $q->param($USER), $q->param($FOLDER));
my $is_admin = grep { $_ eq $remote_user } @{$global_config->{$GLOBAL_ADMINS}};
$user = $remote_user if not $is_admin;
my $user_config = $user && $global_config->{$GLOBAL_USERS}{$user};

my $folder_config = $folder && read_config($folder_configs, $folder);

my ($download_file) = ($q->param($DOWNLOAD_FILE) or "") =~ /^([A-Za-z0-9\.]+)$/;

# List of folders and users
my @folders = grep {length} map {(/^([A-Za-z0-9]+)$/)[0]} $q->param($FOLDERS);
my @users = grep {length} map {(/^([A-Za-z0-9]+)$/)[0]} $q->param($USERS);

my @all_folders = dir_list($global_config->{$GLOBAL_FOLDER_CONFIGS});
my @all_users = keys %{$global_config->{$GLOBAL_USERS}};
@all_users = intersect(\@all_users, [$remote_user]) unless $is_admin;

# Dates
my ($date, $start_date, $end_date) =
    map {UnixDate($q->param($_), $DATE_FORMAT)} ($DATE, $START_DATE, $END_DATE);

# Flags
my $only_most_recent = $q->param($ONLY_MOST_RECENT) ? 1 : 0;

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
if ($q->param($ACTION_DOWNLOAD_FILE)) {
    download();
} else {
    print $q->header();
    print $q->start_html(-title=>$global_config->{$GLOBAL_TITLE}), "\n";
#    print $q->h1($global_config->{$GLOBAL_TITLE}), "\n";
    print $q->start_div({-style=>"float:left"});
    browse_folders();
    print $q->end_div();
#position:absolute;
#
    print $q->start_div({-style=>"float:right"});
    search_form();
    print $q->hr();
    if ($q->param($ACTION_UPLOAD_FILES)) { upload(); }
    if ($q->param($ACTION_CHECK_FOLDER)) { check_folder(); }
    if ($q->param($ACTION_FIND_FILES)) { search_results(); }
    if ($q->param($ACTION_FIND_FOLDERS)) { folder_results(); }
    print $q->end_div();
    print $q->end_html(), "\n";
}

################################
# Actions
################################

sub download {
    my $filename =
        join('/', $DIR, $folder_files, $folder, $user, $date, $download_file);
    print $q->header(-type=>$HEADER_OCTET_STREAM,
                     -attachment=>$download_file,
                     -Content_length=>-s $filename);
    copy($filename, *STDOUT) or die; # TODO: error message
}

sub browse_folders {
    print $q->h2("Browse"), "\n";
    print $q->start_ul(), "\n";
    foreach my $folder (list_folders()) {
        my $folder_config = read_config($folder_configs, $folder);
        print $q->li($q->a({-href=>form_url(
                                 $USERS, $user,
                                 $FOLDERS, $folder,
                                 $ACTION_FIND_FILES, 1,
                                 $ACTION_FIND_FOLDERS, 1)},
                         $folder_config->{$FOLDER_NAME} . ":",
                         $folder_config->{$FOLDER_TITLE},
                         " (due $folder_config->{$FOLDER_DUE})")), "\n";
    }
    print $q->end_ul(), "\n";
}


sub upload {
    my $target_dir = join('/', $DIR, $folder_files, $folder, $user,
                          UnixDate("now", $DATE_FORMAT));
    make_path($target_dir);

    if (not -d $target_dir) {
        sleep 1;
        print "ERROR: upload failed, please retry";
    } else {
        foreach my $file ($q->upload($UPLOAD_FILE)) {
            die if not $file;
            my ($name) = $file =~ /([A-Za-z0-9\. ]+)$/;
            print "Uploading: $name";
            move($q->tmpFileName($name), "$target_dir/$name");
        }
    }
}

sub check_folder {
    my $folder = join('/',$DIR,$folder_files,$folder,$user,$date);

    if (not -d $folder) { die; }

    print $q->h2('Checking uploaded files'), "\n";

    foreach my $checker (@{$folder_config->{$FOLDER_CHECKERS}}) {
        system @$checker, $folder;
    }
}

sub search_form {
#    print $q->h2('Search'), "\n";

    print start_form();
    print $q->start_div();
#    print $q->start_table();
#    print $q->Tr($q->td(["User", "Folder", "Date"]));
#    print $q->start_Tr({-valign=>'top'});
    print "User: ", $q->scrolling_list(
                     -name=>$USERS, -values=>\@all_users,
                     -default=>\@all_users, -multiple=>1, -size=>3), "\n";
    print "Folder: ", $q->scrolling_list(
                     -name=>$FOLDERS, -values=>\@all_folders,
                     -default=>\@all_folders, -multiple=>1, -size=>3), "\n";
    print "Start", $q->textfield(-name=>$START_DATE, -size=>10), "\n";
    print "End", $q->textfield(-name=>$END_DATE, -size=>10), "\n";
    print $q->checkbox(-name=>$ONLY_MOST_RECENT, -label=>'Only most recent'), "\n";
#    print $q->end_Tr();
#    print $q->end_table();

    print $q->submit($ACTION_FIND_FILES, "Search"), "\n";
#    print $q->submit($ACTION_FIND_FOLDERS, "Find folders for uploading"), "\n";
    print $q->end_div();
    print $q->end_form();
}

sub folder_results {
    print $q->h2("Folders for Uploading"), "\n";
    print $q->start_table({-border=>2}), "\n";
    foreach my $folder (list_folders()) {
        my $folder_config = read_config($folder_configs, $folder);
        print $q->h3($folder_config->{$FOLDER_NAME} . ":",
                     $folder_config->{$FOLDER_TITLE},
                     " (due $folder_config->{$FOLDER_DUE})"), "\n";
        print $q->p($folder_config->{$FOLDER_TEXT}), "\n";

        print start_form();
        print $q->hidden(-name=>$FOLDER, -value=>$folder_config->{$FOLDER_NAME},
                         -override=>1), "\n";
        for (my $i = 0; $i < $folder_config->{$FOLDER_FILE_COUNT}; $i++) {
            print $q->p("File", $i+1 . ":",
                        $q->filefield(-name=>$UPLOAD_FILE, -override=>1)), "\n";
        }
        print $q->p($q->checkbox(-name=>$ACTION_CHECK_FOLDER,
                                 -checked=>1, -override=>1,
                                 -label=>"Check after upload")), "\n";
        print $q->submit($ACTION_UPLOAD_FILES, "Upload files"), "\n";
        print $q->end_form(), "\n";
    }
    print $q->end_table(), "\n";
}

sub search_results {
    my %rows;
    foreach my $folder (list_folders()) {
        my $folder_config = read_config($folder_configs, $folder);
        foreach my $user (list_users($folder)) {
            my $user_config = $global_config->{$GLOBAL_USERS}{$user};
            foreach my $date (list_dates($folder, $user)) {
                my $key = join "\0", $folder, $user, $date;

                $rows{$key} = $q->start_Tr() . "\n";
                $rows{$key} .=
                    $q->td([$folder, $folder_config->{$FOLDER_TITLE},
                            $user, $user_config->{$USER_FULL_NAME},
                            $date,
                            $q->a({-href=>form_url(
                                        $ACTION_CHECK_FOLDER, 1,
                                        $FOLDER, $folder, $USER, $user,
                                        $DATE, $date)}, "[check]")]) . "\n";

                my $first = 1;
                foreach my $file (sort (list_files($folder, $user, $date))) {
                    unless ($first) {
                        $rows{$key} .= $q->end_Tr() . $q->start_Tr();
                        $rows{$key} .= $q->td({colspan=>6});
                    }
                    $first = 0;

                    my $filename = join '/',
                        $DIR, $folder_files, $folder, $user, $date, $file;

                    $rows{$key} .= $q->td(
                        $q->a({-href=>form_url($ACTION_DOWNLOAD_FILE, 1,
                                               $FOLDER, $folder,
                                               $USER, $user,
                                               $DATE, $date,
                                               $DOWNLOAD_FILE, $file)},
                              $file));
                    $rows{$key} .= $q->td({-align=>'right'}, -s $filename);
                }
                $rows{$key} .= $q->end_Tr();
            }
        }
    }

    print $q->h2("Uploaded Files"), "\n";
    print $q->start_table({-border=>2}), "\n";
    print $q->thead(
        $q->Tr($q->th(["Folder", "Title", "User", "Name",
                       "Date", "Check", "File", "Size (bytes)"]))), "\n";
    foreach my $key (sort keys %rows) { print $rows{$key}, "\n"; }
    print $q->end_table(), "\n";
}

################
# Listings
################

sub list_folders { return intersect(\@folders, \@all_folders); }
sub list_users { return intersect(\@users, \@all_users); }
sub list_dates {
    my ($folder, $user) = @_;
    my @dates = dir_list($folder_files, $folder, $user);
    @dates = grep {$start_date le $_} @dates if $start_date;
    @dates = grep {$end_date ge $_} @dates if $end_date;
    @dates = ($dates[$#dates]) if $#dates != -1 and $only_most_recent;    
    return @dates;
}

sub list_files {
    my ($folder, $user, $date) = @_;
    return dir_list($folder_files, $folder, $user, $date);
}

################
# CGI Utility
################

# Expects: ($key1 => $val1, $key2 => $val2)
# Returns: $cgi_url?$key1&$val1&$key2&val2
sub form_url {
    my (%params) = @_;
    return $global_config->{$GLOBAL_CGI_URL} . "?" .
        join("&", map {$_ . "=" . $params{$_}} keys %params);
}

sub start_form {
    return $q->start_form(-method=>'POST',
                          -action=>$global_config->{$GLOBAL_CGI_URL},
                          -enctype=>&CGI::MULTIPART);
}

################
# General Util
################

sub read_config {
    my $filename = join '/', $DIR, @_;
    local $/;
    open(my $fh, '<', $filename) or print "No file $filename\n"; # TODO
    return decode_json(<$fh>);
}

sub intersect {
    my ($a, $b) = @_;
    my %a = map {($_,1)} @$a;
    return grep {$a{$_}} @$b;
}

#sub error {
#    my $error = shift;
#    print $q->header(-status=>$error),
#    $q->start_html('Problems'),
#    $q->h2('Request not processed'),
#    $q->strong($error),
#    $q->Dump;
#    exit 0;
#}

sub dir_list {
    my $dir = join '/', $DIR, @_;

    my $d = DirHandle->new($dir);
    my @ds = $d ? $d->read : ();
    $d->close if $d;
    @ds = grep {!/^\./} @ds; # skip dot files
    @ds = grep {!/~$/} @ds; # skip backup files
    return sort @ds;
}
