#! /usr/bin/perl -wT

use strict;
$|++;

use CGI q/-nostiky -private_tempfiles/;
use File::Copy;
use JSON; # install
use DirHandle;
use FileHandle;
use Date::Manip; #TODO install

# File Paths
my $DIR="/u-/adamsmd/projects/upload/tmp";
my $GLOBAL_CONFIG_FILE=$DIR . "/global.config";
my $UPLOAD_CONFIG_DIR=$DIR . '/assignments'; # from global config
my $UPLOAD_DIR=$DIR . '/assignment'; # from global config
my $USER_CONFIG_DIR=$DIR . '/users'; # from global config
my $CGI_SCRIPT="upload.cgi";

# Strings
my $TITLE="title"; # TODO: from global config

# CGI Constants
#my $ACTION="action";
#my $ACTION_PRE_UPLOAD="pre_upload";
#my $ACTION_POST_UPLOAD="post_upload";
#my $ACTION_PRE_DOWNLOAD="pre_download";
#my $ACTION_POST_DOWNLOAD="post_download";
my $ACTION_DOWNLOAD="download";

my $USERS="users";
my $GROUPS="groups";
my $UPLOADS="uploads";
my $START_DATE="start";
my $END_DATE="end";
my $SHOW_EMPTY="show_empty";
#
my $UPLOAD="upload";
#my $FILE="file";
#my $USER="user";
#my $GROUP="group";
#my $START_DATE="start_date";
#my $END_DATE="end_date";
#my $DATE="date";
#my $ONLY_MOST_RECENT="only_most_recent";

# CONFIG constants
my $UPLOAD_TITLE = "title";
my $UPLOAD_MESSAGE = "message";
my $UPLOAD_DUE = "due";
my $UPLOAD_FILE_COUNT = "file-count";

# Must be able to show student interface to admin
# or make it clear what the student doesn't see

my $q = CGI->new;

my $error = $q->cgi_error();
if ($error) { error($error); }

# TODO: Load global config

my ($user) = $ENV{REMOTE_USER} =~ /([A-Za-z0-9]*)/;
$user = 'adamsmd';

# TODO: Load user config

if (defined $q->param($ACTION_DOWNLOAD)) {
    print $q->header(); # TODO: not html
    download();
} else {
    print $q->header();
    print $q->start_html(-title=>$TITLE), "\n";

#    if (defined $q->param($ACTION_UPLOAD)) { upload(); }
#    if (defined $q->param($ACTION_)) { validate(); }
#    search_form();
#    if (defined $q->param('search')) {
search_results();
#}

    print $q->end_html(), "\n";
}

################################
# Actions
################################

sub download {
#    my $q_upload = $q->param($UPLOAD);
#    my $q_user = $q->param($USER); # if not-admin then user=login
#    my $q_date = $q->param($DATE);
##    copy($file, STDOUT);
}


sub upload {
#    my ($upload_name, $upload_config) = upload_config();
#
#    my $target_dir = mkdir_p($UPLOAD_DIR,
#                             $upload_name, $user, time_string());
#
#    if (not $target_dir) { # mask?
#        sleep 1;
#        print "ERROR: upload failed, please retry";
#    } else {
#        # TODO: what if file isn't uploaded? (it is skipped)
#        # TODO: reset on upload field
#        foreach my $file ($q->upload($FILE)) {
#            my ($name) = $file =~ /([A-Za-z0-9\.]+)$/;
#            # TODO print progress and success
#            # TODO: use close upload and rename instead of copy
#            print "Param: $name";
#            print copy($file, "$target_dir/$name");
#        }
#    }
}

sub search_form {
#    start_form($ACTION_PRE_DOWNLOAD);
#
#    # if admin then list users else current user
#    my @users = ("user1", "user2", "user3");
#    # TODO: unselect all
#    print "User:"; print $q->scrolling_list($USERS, \@users);
#
#    # TODO: admin controls on user-group
#    my @groups = ("group1");
#    print "user-group"; print $q->scrolling_list($GROUPS, \@groups);
#
#    my @uploads = dir_list($UPLOAD_CONFIG_DIR);
#    print "Assignment:";
#    print $q->scrolling_list($UPLOAD, \@uploads); # TODO: (select some or none)
#
#    #print $q->text(-name=>$START_DATE, {class: 'date'});
#    #print $q->text(-name=>$END_DATE, {class: 'date'});
#
#    print $q->checkbox(-name=>$ONLY_MOST_RECENT, -label=>'Only most recent');
#
#    print $q->submit();
#    print $q->end_form();
#
##    window.addEvent('load', function() {
##        new DatePicker('.demo_vista', { pickerClass: 'datepicker_vista' });
#
}

sub search_results {
    my $show_empty = $q->param($SHOW_EMPTY);

    my $root = "root";
    my $tree = [];
    my $show_upload = 0;  # show new (only if upload is first in list)
    my $show_user = 1; #show empty (only if upload or user)
    foreach my $upload (uploads()) {
        my @upload = ($upload, upload_line($upload));
        path($tree, $root, @upload) if $show_upload;
        foreach my $user (users($upload)) {
            my @user = ($user, $user);
#            my @user_upload = (@upload, @user);
            my @user_upload = (@user, @upload);
#            my @user_upload = (@upload);
#            my @user_upload = (@user);
#            my @user_upload = ();
            path($tree, $root, @user_upload) if $show_user;
            foreach my $date (dates($upload, $user)) {
                my @date = ("$date/$user/$upload", $date);
                # or "upload/user" or "user/date/upload", i.e., sort by
                path($tree, $root, @user_upload, @date);
                foreach my $file (files($upload,$user,$date)) {
                    my @file = ($file, $file);
                    path($tree, $root, @user_upload, @date, @file);
                }
            }
        }
        
    }

    print_tree(0, $tree);

}

# TODO: upload filename regex

# NOTE: Dates may not be unique

sub uploads {
    return ("upload1", "upload2");
    my @uploads = dir_list($UPLOAD_CONFIG_DIR);
    my @q_uploads = param_list($UPLOADS, @uploads);
    return intersect(@q_uploads, @uploads);
}

sub upload_line {
    my ($upload) = @_;
    #my ($upload_name, $upload_config) = upload_config($upload);
    my ($upload_name, $upload_config) =
        ("$upload", {$UPLOAD_TITLE => "title",
                     $UPLOAD_MESSAGE => "message",
                     $UPLOAD_DUE => "due"});
    return
        ($q->start_form(
             -method=>'POST',
             -action=>$CGI_SCRIPT,
             -enctype=>'multipart/form-data') .
         $q->hidden(-name=>$UPLOAD, -value=>$upload_name) . "\n" . # TODO: check about stiky
         $q->h1($upload_config->{$UPLOAD_TITLE}) . "\n" .
         $q->p($upload_config->{$UPLOAD_MESSAGE}) . "\n" .
         $q->p($upload_config->{$UPLOAD_DUE}) . "\n" .
#        for (my $i = 0; $i < $upload_config->{$UPLOAD_FILE_COUNT}; $i++) {
#            print $q->filefield(-name=>$FILE), "\n";
#        }
         $q->submit() . "\n".         
         $q->end_form());

}

sub users { # TODO: filter by group
    # if none then all
    # if not-admin then user=login
    return ("user1", "user2");
    my ($upload) = @_;
    my @c_users = dir_list($USER_CONFIG_DIR);
    my @q_users = param_list($USERS, @c_users);
    my @c_groups = (); # TODO
    my @groups = param_list($GROUPS, @c_groups); # as list?
    #my @d_users = dir_list($UPLOAD_DIR . '/' . $upload);
    return intersect(@q_users, @c_users);
}

sub dates { # TODO: filter by start and end date only most recent
    return ("date1", "date2");
    my $start = $q->param($START_DATE);
    my $end = $q->param($END_DATE);
    my ($upload, $user) = @_;
    my @dates = dir_list($UPLOAD_DIR . '/' . $upload . '/' . $user);
    if ($#dates == -1) { return "speudo_date"; }
    else { return @dates; }
}

#                # TODO: is overdue
#                # TODO: zebra stripes
sub files {
    return ("file1", "file2");
}

sub file_line {
#                print $q->Tr(
#                    $q->td({rowspan=>n}, [$assignment, $user, $date]),
#                    map { $q->td(file); $q->td(size); } @files);
}

################

sub path {
    my ($tree, @path) = @_;
    my ($info, $name);
    while (1) {
        ($info, @path) = @path;
        $tree->[0] = $info;
        last if $#path == -1;

        ($name, @path) = @path;
        $tree = $tree->[1]{$name} = $tree->[1]{$name} || [];
        last if $#path == -1;
    }
}

sub print_tree {
    my ($nesting, $tree) = @_;
    print " "x$nesting, $tree->[0], "\n";
    foreach my $key (sort keys %{$tree->[1]}) {
        print_tree($nesting+1, $tree->[1]{$key});
    }
}

################
# Config Files
################

sub global_config { }

sub user_config { }

sub upload_config {
#    my ($upload) = $q->param($UPLOAD) =~ /([A-Za-z0-9]*)/;
#    # check assignment is valid
#    local $/;
#    open(my $fh, '<', $UPLOAD_CONFIG_DIR . '/' . $upload);
#    my $json_text   = <$fh>;
#    my $perl_scalar = decode_json($json_text);
#    return ($upload, $perl_scalar);
#
#    description
#    upload msg
#    [(file-id, max size, filename pattern)]
#    due date
#    post processor (optional)

}

################
# Utility
################

sub start_form {
    my $action = shift;
    print $q->start_form(
        -method=>'POST',
        -action=>$CGI_SCRIPT,
        -enctype=>'multipart/form-data'), "\n";
#    $q->param($ACTION, $action);
#    print $q->hidden(-name=>$ACTION, -value=>$action), "\n";
}

sub error {
    my $error = shift;
    print $q->header(-status=>$error),
    $q->start_html('Problems'),
    $q->h2('Request not processed'),
    $q->strong($error);
    exit 0;
}

sub dir_list {
    my ($dir) = shift;
    my $d = DirHandle->new($dir);
    if (defined $d) {
        my @ds = $d->read;
        $d->close;
        @ds = grep {!/^\./} sort @ds; # TODO skip backup files
        return @ds;
    }
}

sub time_string {
    my ($sec,$min,$hour,$mday,$mon,$year,$wday,$yday,$isdst) = localtime();
    return sprintf("%04d-%02d-%02dT%02d:%02d:%02d",
                   $year+1900, $mon, $mday, $hour, $min, $sec);
}

sub mkdir_p {
    my $dir;
    for ($dir = shift; $#_ >= 0; $dir = $dir . "/" . shift) {
        mkdir $dir;
        #if (not (-d $dir or mkdir $dir)) {
        #    print $dir;
        #    print "zz" . getpwuid($<);
        #    return 0;
        #}
    }
    print "$dir";
    if (mkdir $dir) { return $dir; }
    return 0;
}
