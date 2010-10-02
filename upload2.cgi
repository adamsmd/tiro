#! /usr/bin/perl -wT

use strict;
$|++;

use CGI q/-nostiky -private_tempfiles/;
use File::Copy;
use File::Path;
use JSON; # install
use DirHandle;
use FileHandle;
use Date::Manip; #TODO install
use Memoize;

# TODO: date
# TODO: taint checking

# File Paths
#my $DIR="/u-/adamsmd/projects/upload/tmp";
my $DIR="demo";
my $GLOBAL_CONFIG_FILE="global_config.json";

# CGI Constants
my $ACTION_DOWNLOAD="download";
my $ACTION_UPLOAD="do_upload";
my $ACTION_SEARCH="search";
my $ACTION_SEARCH_UPLOADS="search_uploads";
my $ACTION_VALIDATE="validate";

my $USERS="users";
my $GROUPS="groups";
my $UPLOADS="uploads";
my $START_DATE="start_date"; # includes "any"
my $END_DATE="end_date"; # includes "any"
my $SHOW_EMPTY="show_empty";
my $SHOW_NEW_UPLOAD="show_new_upload";
my $ONLY_MOST_RECENT="only_most_recent";

# Upload constants
my $UPLOAD="upload";
my $USER="user";
my $FILE="file";
my $DATE="date";

# CONFIG constants
my $GLOBAL_TITLE = 'title';
my $GLOBAL_UPLOAD_CONFIGS = 'upload_configs';
my $GLOBAL_UPLOAD_FILES = 'upload_files';
my $GLOBAL_USER_CONFIGS = 'user_configs';
my $GLOBAL_CGI_URL = 'cgi_url';
my $GLOBAL_PATH = 'path'; # Path to search for validators

my $UPLOAD_NAME = "name";
my $UPLOAD_TITLE = "title";
my $UPLOAD_MESSAGE = "message";
my $UPLOAD_DUE = "due";
my $UPLOAD_FILE_COUNT = "file-count";
my $UPLOAD_VALIDATORS = "validators";
#    my $show_empty = $q->param($SHOW_EMPTY);
#    my $show_new_upload = $q->param($SHOW_NEW_UPLOAD);
#    my $show_upload = 1;  # show new (only if upload is first in list)
#    my $show_user = 1; #show empty (only if upload or user)
# TODO: file_size
# TODO: file_name regex

my $USER_NAME = 'user_name';
my $USER_FULL_NAME = 'full_name';

my $DATE_FORMAT = "%O";

memoize('read_config');
memoize('dir_list');

# TODO: Must be able to show student interface to admin
# or make it clear what the student doesn't see

my $q = CGI->new;

my $error = $q->cgi_error();
if ($error) { error($error); }

my $global_config = read_config($GLOBAL_CONFIG_FILE);

my ($user) = $q->remote_user() =~ /([A-Za-z0-9]*)/;
# TODO: $q->remote_user();

# TODO: -override

# TODO: Load user config

if (defined $q->param($ACTION_DOWNLOAD)) {
    print $q->header(); # TODO: not html
    download();
} else {
    #print $q->header();
    print $q->start_html(-title=>$global_config->{$GLOBAL_TITLE}), "\n";

    print $q->h1($global_config->{$GLOBAL_TITLE}), "\n";
    if (defined $q->param($ACTION_UPLOAD)) { upload(); }
    if (defined $q->param($ACTION_VALIDATE)) { validate(); }
    search_form();
    if (defined $q->param($ACTION_SEARCH_UPLOADS)) { upload_results(); }
    if (defined $q->param($ACTION_SEARCH)) { search_results(); }

    print $q->end_html(), "\n";
}

################################
# Actions
################################

sub download {
    my ($upload, $user, $date) = filename_param($UPLOAD, $USER, $DATE);
    # if not-admin then user=login

    # validate input
    # print header
    # copy($file, STDOUT);
}

sub upload {
    my ($upload, $user) = filename_param($UPLOAD, $USER);

    my $upload_config = upload_config($upload);

    my $target_dir = make_path(
        $global_config->{$GLOBAL_UPLOAD_FILES} . '/' .
        $upload_config->{$UPLOAD_NAME} . '/' .
        $user . '/' . UnixDate("now", $DATE_FORMAT));

    if (not $target_dir) { # mask?
        sleep 1;
        print "ERROR: upload failed, please retry";
    } else {
        # TODO: what if file isn't uploaded? (it is skipped)
        # NOTE: upload multiple file w/ same name
        foreach my $file ($q->upload($FILE)) {
            my ($name) = $file =~ /([A-Za-z0-9\.]+)$/;
            # TODO print progress and success
            # TODO: use close upload and rename instead of copy
            print "Name: $name";
#            print copy($file, "$target_dir/$name");
        }
    }
}

sub validate {
    print $q->h2('Validation'), "\n";
    my ($upload, $user, $date) = filename_param($UPLOAD, $USER, $DATE);
    # TODO: filter $date by "last"
    # TODO: check that exists and have permissions

    my $upload_config = upload_config($upload);
    foreach my $validator (@{$upload_config->{$UPLOAD_VALIDATORS}}) {
        ($ENV{PATH}) = $global_config->{$GLOBAL_PATH} =~ /^(.*)$/; #TODO: insecure
        my ($upload_files) =
            $global_config->{$GLOBAL_UPLOAD_FILES} =~ /([A-Za-z0-9]*)/;
        # TODO: why is $upload_files tainted
        system @$validator, join('/', $upload_files, $upload, $user, $date);
    }
}

sub search_form {
    print $q->h2('Search'), "\n";

    print start_form();

    # if admin then list users else current user
    my @users = dir_list($global_config->{$GLOBAL_USER_CONFIGS});
    # TODO: unselect all
    print $q->start_table();
    print $q->Tr($q->td(["User", "Assignment", "Date"]));
    print $q->start_Tr({-valign=>'top'});
    print $q->td($q->scrolling_list(
                     -name=>$USERS, -values=>\@users, -multiple=>1)), "\n";

#    # TODO: admin controls on user-group
#    my @groups = ("group1");
#    print "user-group"; print $q->scrolling_list($GROUPS, \@groups);

    my @uploads = dir_list($global_config->{$GLOBAL_UPLOAD_CONFIGS});

    print $q->td($q->scrolling_list(
        -name=>$UPLOAD,
        -values=>\@uploads,
        -multiple=>1)), "\n"; # TODO: (select some or none)

    print $q->td(
        "Start", $q->input({-class => 'date', -name=>$START_DATE}), $q->br,
        "End", $q->input({-class => 'date', -name=>$END_DATE}), $q->br,
        $q->checkbox(-name=>$ONLY_MOST_RECENT,
                     -label=>'Only most recent'));
# TODO: most recent != last

    print $q->end_Tr();
    print $q->end_table();

    print $q->submit($ACTION_SEARCH, "Search"), "\n";
    print $q->submit($ACTION_SEARCH_UPLOADS, "Search Uploads"), "\n";
    print $q->end_form();

#    window.addEvent('load', function() {
#        new DatePicker('.demo_vista', { pickerClass: 'datepicker_vista' });

}

sub upload_results {
    print $q->h2("Uploads"), "\n";
    print $q->start_table({-border=>2}), "\n";
    foreach my $upload (list_uploads()) {
        my $upload_config = upload_config($upload);
        print $q->h3($upload_config->{$UPLOAD_NAME} . ":",
                     $upload_config->{$UPLOAD_TITLE},
                     " (due $upload_config->{$UPLOAD_DUE})"), "\n";
        print $q->p($upload_config->{$UPLOAD_MESSAGE}), "\n";

        print start_form();
        print $q->hidden(
            -name=>$UPLOAD, -value=>$upload_config->{$UPLOAD_NAME}), "\n";
        # TODO: check about stiky
        for (my $i = 0; $i < $upload_config->{$UPLOAD_FILE_COUNT}; $i++) {
            print $q->p("File", $i+1 . ":", $q->filefield(-name=>$FILE)), "\n";
        }
        print $q->p(
            $q->checkbox(-name=>$ACTION_VALIDATE,
                         -checked=>1, # TODO: why isn't checked working?
                         -label=>"Validate")), "\n";
        print $q->submit($ACTION_UPLOAD, "Upload files"), "\n";
        print $q->end_form(), "\n";
    }
    print $q->end_table(), "\n";
}

sub search_results {
    my %rows;
    foreach my $upload (list_uploads()) {
        my $upload_config = upload_config($upload);
        foreach my $user (list_users($upload)) {
            my $user_config = user_config($user);
            foreach my $date (list_dates($upload, $user)) {
                my $key = "$upload\0$user\0$date";

                $rows{$key} = $q->start_Tr() . "\n";
                $rows{$key} .=
                    $q->td([$upload, $upload_config->{$UPLOAD_TITLE},
                            $user, $user_config->{$USER_FULL_NAME},
                            $date . " " .
                            $q->a({-href=>form_url(
                                        $ACTION_VALIDATE, $ACTION_VALIDATE,
                                        $UPLOAD, $upload, $USER, $user,
                                        $DATE, $date)}, "[check]")]) . "\n";

                my $first = 1;
                foreach my $file (sort (list_files($upload, $user, $date))) {
                    unless ($first) {
                        $rows{$key} .= $q->end_Tr() . $q->start_Tr();
                        $rows{$key} .= $q->td({colspan=>5});
                    }
                    $first = 0;

                    my $filename =
                        "$DIR/$global_config->{$GLOBAL_UPLOAD_FILES}/" .
                        "$upload/$user/$date/$file";

                    $rows{$key} .= $q->td(
                        $q->a({-href=>form_url($ACTION_DOWNLOAD, 1,
                                               $UPLOAD, $upload,
                                               $USER, $user,
                                               $DATE, $date)},
                              $file));
                    $rows{$key} .= $q->td({-align=>'right'}, -s $filename);
                }
                $rows{$key} .= $q->end_Tr();
            }
        }
    }
    # TODO: is overdue
    # TODO: zebra stripes

    print $q->h2("Results"), "\n";
    print $q->start_table({-border=>2}), "\n";
    print $q->thead($q->Tr($q->th(["Upload", "Title", "User", "Name",
                                   "Date", "File", "Size (bytes)"]))), "\n";
    foreach my $key (sort keys %rows) { print $rows{$key}, "\n"; }
    print $q->end_table(), "\n";
}

################
# Listing Functions
################

sub list_uploads {
    my @c_uploads = dir_list($global_config->{$GLOBAL_UPLOAD_CONFIGS});
    my @q_uploads = $q->param($UPLOADS);
    return intersect(\@q_uploads, \@c_uploads);
}

# TODO: select multiple validators
# TODO: if none, then all?

sub list_users { # TODO: filter by group
    # if not-admin then user=login
    my ($upload) = @_;

    my @c_users = dir_list($global_config->{$GLOBAL_USER_CONFIGS});
    my @q_users = $q->param($USERS);
    #my @c_groups = (); # TODO
    #my @groups = filenames_param($GROUPS, @c_groups); # as list? (none -> no filter)
    #my @d_users = dir_list($UPLOAD_DIR . '/' . $upload);
    return intersect(\@q_users, \@c_users);
}

# TODO: sort by fullname vs by username

sub list_dates { # TODO: filter by start and end date only most recent
    my ($upload, $user) = @_;

    my @dates = dir_list(
        $global_config->{$GLOBAL_UPLOAD_FILES}, $upload, $user);

    my $start_date = $q->param($START_DATE);
    if (defined $start_date) {
        $start_date = UnixDate($start_date, $DATE_FORMAT);
        @dates = grep {$start_date le $_} @dates;
    }

    my $end_date = $q->param($END_DATE);
    if (defined $end_date) {
        $end_date = UnixDate($end_date, $DATE_FORMAT);
        @dates = grep {$end_date ge $_} @dates;
    }

    if ($#dates != -1 and defined $q->param($ONLY_MOST_RECENT)) {
        @dates = ($dates[$#dates]);
    }
    
    return @dates;
}

sub list_files {
    my ($upload, $user, $date) = @_;
    return dir_list(
        $global_config->{$GLOBAL_UPLOAD_FILES}, $upload, $user, $date);
}

################
# Config Files
################

# TODO: cache configs

sub user_config {
    my ($user) = @_;
    my $config = read_config($global_config->{$GLOBAL_USER_CONFIGS}, $user);
    # TODO: assert $config->{$USER_NAME} == $user_name (and other configs)
    return $config;
}

sub upload_config {
#        file_size => 'file_size',
#        file_regex => 'file_regex',

    my ($upload) = @_;
    return read_config($global_config->{$GLOBAL_UPLOAD_CONFIGS}, $upload);
    # check assignment is valid
}

sub read_config {
    my $filename = join '/', $DIR, @_;
    local $/;
    open(my $fh, '<', $filename) or print "No file $filename\n"; # TODO
    return decode_json(<$fh>);
}

################
# CGI Utility
################

# Expects: {$key1 => $val1, $key2 => $val2}
# Returns: $cgi_url?$key1&$val1&$key2&val2
sub form_url {
    my (%params) = @_;
    return "$global_config->{$GLOBAL_CGI_URL}?" .
        join("&", map {$_ . "=" . $params{$_}} keys %params);
}

sub filename_param {
    return map {
        my $param = $q->param($_);
        (defined $param) ? ($param =~ /^([A-Za-z0-9]*)$/)[0] : undef;
    } @_;
}

sub start_form {
    return $q->start_form(
        -method=>'POST',
        -action=>$global_config->{$GLOBAL_CGI_URL},
        -enctype=>'multipart/form-data');
}

################
# General Util
################
sub intersect {
    my ($a, $b) = @_;
    my %a = map {($_,1)} @$a;
    return grep {$a{$_}} @$b;
}

sub error {
    my $error = shift;
    print $q->header(-status=>$error),
    $q->start_html('Problems'),
    $q->h2('Request not processed'),
    $q->strong($error),
    $q->Dump;
    exit 0;
}

sub dir_list {
    my $dir = join '/', $DIR, @_;

    my $d = DirHandle->new($dir);
    if (defined $d) {
        my @ds = $d->read;
        $d->close;
        @ds = grep {!/^\./} @ds; # skip dot files
        @ds = grep {!/~$/} @ds; # skip backup files
        return sort @ds;
    } else {
        # TODO: test upload dir not existing
        print "ERROR: $dir\n"; # TODO
        return ();
    }
}
