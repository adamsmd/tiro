#! /usr/bin/perl -wT

use strict;
$|++;

use CGI q/-nostiky -private_tempfiles/;
use File::Copy;
use JSON;
use DirHandle;
use FileHandle;
use Date::Manip; #TODO

# File Paths
my $DIR="/u-/adamsmd/projects/upload/tmp";
my $GLOBAL_CONFIG_FILE=$DIR . "/global.config";
my $UPLOAD_CONFIG_DIR=$DIR . '/assignments'; # from global config
my $UPLOAD_DIR=$DIR . '/assignment'; # from global config
my $USER_CONFIG_DIR=$DIR . '/users'; # from global config
my $CGI_SCRIPT="upload.cgi";

# Strings
my $TITLE="title";

# CGI Constants
my $ACTION="action";
my $ACTION_PRE_UPLOAD="pre_upload";
my $ACTION_POST_UPLOAD="post_upload";
my $ACTION_PRE_DOWNLOAD="pre_download";
my $ACTION_POST_DOWNLOAD="post_download";

my $UPLOAD="upload";
my $FILE="file";
my $USER="user";
my $GROUP="group";
my $START_DATE="start_date";
my $END_DATE="end_date";
my $DATE="date";
my $ONLY_MOST_RECENT="only_most_recent";

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

my $action = $q->param($ACTION);

if ($action eq $ACTION_POST_DOWNLOAD) {
    print $q->header(); # TODO: not html
    post_download();
} else {
    print $q->header();
    print $q->start_html(-title=>$TITLE);

    if (not defined $action) { select_upload(); select_download(); }
    elsif ($action eq $ACTION_PRE_UPLOAD) { pre_upload(); }
    elsif ($action eq $ACTION_POST_UPLOAD) { post_upload(); }
    elsif ($action eq $ACTION_PRE_DOWNLOAD) { pre_download(); }
    else {
        #error unknown action;
    }

    print $q->end_html(), "\n";
}


sub select_upload {
    start_form($ACTION_PRE_UPLOAD);
    
    my @uploads = dir_list($UPLOAD_CONFIG_DIR);
    print $q->scrolling_list($UPLOAD, \@uploads);

    print $q->submit();
    print $q->end_form();
}

sub pre_upload {
    start_form($ACTION_POST_UPLOAD);
    my ($upload_name, $upload_config) = upload_config();
    print $q->hidden(-name=>$UPLOAD, -value=>$upload_name);
    print $q->h1($upload_config->{$UPLOAD_TITLE}), "\n";
    print $q->p($upload_config->{$UPLOAD_MESSAGE}), "\n";
    print $q->p($upload_config->{$UPLOAD_DUE}), "\n";
    for (my $i = 0; $i < $upload_config->{$UPLOAD_FILE_COUNT}; $i++) {
        print $q->filefield(-name=>$FILE), "\n";
    }
    print $q->submit();
    print $q->end_form();
}

sub post_upload {
    my ($upload_name, $upload_config) = upload_config();

    my $target_dir = mkdir_p($UPLOAD_DIR,
                             $upload_name, $user, time_string());

    if (not $target_dir) { # mask?
        sleep 1;
        print "ERROR: upload failed, please retry";
    } else {
        # TODO: what if file isn't uploaded? (it is skipped)
        # TODO: reset on upload field
        foreach my $file ($q->upload($FILE)) {
            my ($name) = $file =~ /([A-Za-z0-9\.]+)$/;
            # TODO print progress and success
            # TODO: use close upload and rename instead of copy
            print "Param: $name";
            print copy($file, "$target_dir/$name");
        }
    #post_process
    }
}

sub select_download {
    start_form($ACTION_PRE_DOWNLOAD);

    # if admin then list users else current user
    my @users = ("ANY", "x", "y", "z");
    print "User:"; print $q->scrolling_list($USER, \@users); # TODO: labels hash for any

    # TODO: admin controls on user-group
    print "user-group";

    my @uploads = dir_list($UPLOAD_CONFIG_DIR);
    print "Assignment:";
    print $q->scrolling_list($UPLOAD, \@uploads); # TODO: labels hash for any (select some or none)

    #print $q->text(-name=>$START_DATE, {class: 'date'});
    #print $q->text(-name=>$END_DATE, {class: 'date'});

    print $q->checkbox(-name=>$ONLY_MOST_RECENT, -label=>'Only most recent');

    print $q->submit();
    print $q->end_form();


#    window.addEvent('load', function() {
#        new DatePicker('.demo_vista', { pickerClass: 'datepicker_vista' });

}

sub pre_download {
    my @q_users = $q->param($USER); # as list
    # if none then all
    # if not-admin then user=login
    my @q_groups = $q->param($GROUP); # as list?
    my @q_uploads = $q->param($UPLOAD);
    my $q_start = $q->param($START_DATE);
    my $q_end = $q->param($END_DATE);
    my $q_only_most_recent = $q->param($ONLY_MOST_RECENT);

    print $q->start_table();
#foreach $user () {
#    if ($user in $group) {
#        foreach $assignment () {
#            my @dates = dir_list(assignment/user);
#            @dates = grep {between $start and $end} @dates;
#            @dates = last @dates if $q_only_most_recent;
#                           
#            foreach $date (@dates) {
#                my @files = ...;
#
#                # TODO: is overdue
#                # TODO: zebra stripes
#                print $q->Tr(
#                    $q->td({rowspan=>n}, [$assignment, $user, $date]),
#                    map { $q->td(file); $q->td(size); } @files);
#                }
#            }
#        }
#    }
#}
}

sub post_download {
    my $q_upload = $q->param($UPLOAD);
    my $q_user = $q->param($USER); # if not-admin then user=login
    my $q_date = $q->param($DATE);
#    copy($file, STDOUT);
}

################
# Config Files
################

sub global_config { }

sub user_config { }

sub upload_config {
    my ($upload) = $q->param($UPLOAD) =~ /([A-Za-z0-9]*)/;
    # check assignment is valid
    local $/;
    open(my $fh, '<', $UPLOAD_CONFIG_DIR . '/' . $upload);
    my $json_text   = <$fh>;
    my $perl_scalar = decode_json($json_text);
    return ($upload, $perl_scalar);

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
    $q->param($ACTION, $action);
    print $q->hidden(-name=>$ACTION, -value=>$action), "\n";
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
