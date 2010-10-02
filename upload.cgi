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

# TODO: taint checking
#       -param
#       -dir_list
#       -config file contents

# TODO: -override
# TODO: select multiple validators
# TODO: if none, then all?
# TODO: sort by fullname vs by username

# TODO: assert $config->{$USER_NAME} == $user_name (and other configs)
# TODO: check configs are valid

    # TODO: filter by group (as list)
    #my @c_groups = (); # TODO
    #my @groups = filenames_param($GROUPS, @c_groups);


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
my $GLOBAL_POST_MAX = 'post_max';

my $UPLOAD_NAME = "name";
my $UPLOAD_TITLE = "title";
my $UPLOAD_MESSAGE = "message";
my $UPLOAD_DUE = "due";
my $UPLOAD_FILE_COUNT = "file-count";
my $UPLOAD_VALIDATORS = "validators";
# TODO: file_name regex

my $USER_NAME = 'user_name';
my $USER_FULL_NAME = 'full_name';

my $DATE_FORMAT = "%O"; # TODO: Put in global config?

memoize('read_config');
memoize('dir_list');

# TODO: Must be able to show student interface to admin
# or make it clear what the student doesn't see

my $q = CGI->new;

my $error = $q->cgi_error(); # TODO
if ($error) { error($error); }

my $global_config = read_config($GLOBAL_CONFIG_FILE);
$CGI::POST_MAX = $global_config->{$GLOBAL_POST_MAX};
($ENV{PATH}) = $global_config->{$GLOBAL_PATH} =~ /^(.*)$/; #TODO: insecure

my ($upload_files) =
    $global_config->{$GLOBAL_UPLOAD_FILES} =~ /^([A-Za-z0-9_ ]+)$/;

################
# Read inputs
################
my ($remote_user) = ($q->remote_user() or "") =~ /^([A-Za-z0-9]+)$/;
my $is_admin = 1; # TODO

my ($upload) = ($q->param($UPLOAD) or "") =~ /^([A-Za-z0-9]+)$/;
my $upload_config = $upload && upload_config($upload);

my ($user) = ($q->param($USER) or "") =~ /^([A-Za-z0-9]+)$/;
$user = $remote_user if not $is_admin;
my $user_config = $user && user_config($user);

my $date = UnixDate($q->param($DATE), $DATE_FORMAT);
my $start_date = UnixDate($q->param($START_DATE), $DATE_FORMAT);
my $end_date = UnixDate($q->param($END_DATE), $DATE_FORMAT);

# uploads and users
my @uploads = grep {length} map {(/^([A-Za-z0-9]+)$/)[0]} $q->param($UPLOADS);
my @all_uploads = dir_list($global_config->{$GLOBAL_UPLOAD_CONFIGS});
my @users = grep {length} map {(/^([A-Za-z0-9]+)$/)[0]} $q->param($USERS);
my @all_users = dir_list($global_config->{$GLOBAL_USER_CONFIGS});
@all_users = intersect(\@all_users, [$remote_user]) unless $is_admin;

# only most recent
my $only_most_recent = $q->param($ONLY_MOST_RECENT) ? 1 : 0;

# action
# list dates
# upload file

################
# Do work
################
if ($q->param($ACTION_DOWNLOAD)) {
    download();
} else {
    #print $q->header(); # TODO: enable when not debugging
    print $q->start_html(-title=>$global_config->{$GLOBAL_TITLE}), "\n";

    print $q->h1($global_config->{$GLOBAL_TITLE}), "\n";
    if ($q->param($ACTION_UPLOAD)) { upload(); }
    if ($q->param($ACTION_VALIDATE)) { validate(); }
    search_form();
    if ($q->param($ACTION_SEARCH_UPLOADS)) { upload_results(); }
    if ($q->param($ACTION_SEARCH)) { search_results(); }

    print $q->end_html(), "\n";
}

################################
# Actions
################################

sub download {
    # print $q->header(); # TODO: not html
    # copy($file, STDOUT);
}

sub upload {
    my $target_dir = join('/', $upload_files,
                          $upload_config->{$UPLOAD_NAME},
                          $user, UnixDate("now", $DATE_FORMAT));
    make_path($target_dir); # TODO: file mode?

    if (not -d $target_dir) {
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
    # TODO: check that exists and have permissions

    foreach my $validator (@{$upload_config->{$UPLOAD_VALIDATORS}}) {
        system @$validator, join('/', $upload_files, $upload, $user, $date);
    }
}

sub search_form {
    print $q->h2('Search'), "\n";

    print start_form();

    # TODO: unselect all
    print $q->start_table();
    print $q->Tr($q->td(["User", "Assignment", "Date"]));
    print $q->start_Tr({-valign=>'top'});
    print $q->td($q->scrolling_list(
                     -name=>$USERS, -values=>\@all_users, -multiple=>1)), "\n";

#    # TODO: admin controls on user-group
#    my @groups = ("group1");
#    print "user-group"; print $q->scrolling_list($GROUPS, \@groups);

    print $q->td($q->scrolling_list(
        -name=>$UPLOAD,
        -values=>\@all_uploads,
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
    # TODO: sort and filter by due date
    print $q->h2("Uploads"), "\n";
    print $q->start_table({-border=>2}), "\n";
    foreach my $upload (list_uploads()) {
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

                    my $filename = join '/',
                        $DIR, $upload_files, $upload, $user, $date, $file;

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

sub list_uploads { return intersect(\@uploads, \@all_uploads); }
sub list_users { return intersect(\@users, \@all_users); }
sub list_dates {
    my ($upload, $user) = @_;

    my @dates = dir_list($upload_files, $upload, $user);

    @dates = grep {$start_date le $_} @dates if $start_date;
    @dates = grep {$end_date ge $_} @dates if $end_date;

    if ($#dates != -1 and $only_most_recent) {
        @dates = ($dates[$#dates]);
    }
    
    return @dates;
}

sub list_files {
    my ($upload, $user, $date) = @_;
    return dir_list($upload_files, $upload, $user, $date);
}

################
# Config Files
################

sub user_config { read_config($global_config->{$GLOBAL_USER_CONFIGS}, @_); }
sub upload_config { read_config($global_config->{$GLOBAL_UPLOAD_CONFIGS}, @_); }
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
    if ($d) {
        my @ds = $d->read;
        $d->close;
        @ds = grep {!/^\./} @ds; # skip dot files
        @ds = grep {!/~$/} @ds; # skip backup files
        return sort @ds;
    } else {
        return ();
    }
}
