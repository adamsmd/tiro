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
#my $DIR="/u-/adamsmd/projects/upload/tmp";
my $DIR="demo";
#my $GLOBAL_CONFIG_FILE=$DIR . "/global.config";
my $GLOBAL_CONFIG_FILE="$DIR/global_config.json";

# CGI Constants
my $ACTION_DOWNLOAD="download";
my $ACTION_UPLOAD="upload";
my $ACTION_SEARCH="search";
my $ACTION_VALIDATE="validate";

my $USERS="users";
my $GROUPS="groups";
my $UPLOADS="uploads";
my $START_DATE="start";
my $END_DATE="end"; # includes "last"
my $SHOW_EMPTY="show_empty";
my $SHOW_NEW_UPLOAD="show_new_upload";

# Upload constants
my $UPLOAD="upload";
my $USER="user";
my $FILE="file";
my $DATE="date";

# CONFIG constants
my $UPLOAD_NAME = "name";
my $UPLOAD_TITLE = "title";
my $UPLOAD_MESSAGE = "message";
my $UPLOAD_DUE = "due";
my $UPLOAD_FILE_COUNT = "file-count";
my $UPLOAD_VALIDATORS = "validators";

my $GLOBAL_TITLE = 'title';
my $GLOBAL_UPLOAD_CONFIGS = 'upload_configs';
my $GLOBAL_UPLOAD_FILES = 'upload_files';
my $GLOBAL_USER_CONFIGS = 'user_configs';
my $GLOBAL_CGI_URL = 'cgi_url';

# Other constant
my $NESTING_SEP = ',';

# Must be able to show student interface to admin
# or make it clear what the student doesn't see

my $q = CGI->new;

my $error = $q->cgi_error();
if ($error) { error($error); }

my $global_config = read_config($GLOBAL_CONFIG_FILE);

my ($user) = $ENV{REMOTE_USER} =~ /([A-Za-z0-9]*)/;
$user = 'adamsmd';

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
    if (defined $q->param($ACTION_SEARCH)) { search_results(); }

    print $q->end_html(), "\n";
}

# bless to avoid $GLOBAL_TITLE

################################
# Actions
################################

sub download {
    my $upload = $q->param($UPLOAD);
    #my $user = $q->param($USER); # if not-admin then user=login
    #my $date = $q->param($DATE);
    # validate input
    # print header
    # copy($file, STDOUT);
}

sub upload {
    my ($upload) = $q->param($UPLOAD) =~ /([A-Za-z0-9]*)/;
    my ($user) = $q->param($USER) =~ /([A-Za-z0-9]*)/;
    my $upload_config = upload_config($upload);

    my $target_dir = mkdir_p(
        $global_config->{$GLOBAL_UPLOAD_FILES},
        $upload_config->{$UPLOAD_NAME},
        $user, time_string());

    if (not $target_dir) { # mask?
        sleep 1;
        print "ERROR: upload failed, please retry";
    } else {
        # TODO: file_size
        # TODO: file_name regex
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
    my ($upload) = $q->param($UPLOAD) =~ /([A-Za-z0-9]*)/;
    my ($user) = $q->param($USER) =~ /([A-Za-z0-9]*)/;
    my ($date) = $q->param($DATE) =~ /([A-Za-z0-9]*)/; # TODO: filter by "last"
    # TODO: check that exists and permissions

    my $upload_config = upload_config($upload);
    foreach my $validator (@{$upload_config->{$UPLOAD_VALIDATORS}}) {
        # validator
        print "run:", join(
            ":", @$validator,
            join('/', $global_config->{$GLOBAL_UPLOAD_FILES},
                 $upload, $user, $date)), "\n";
        # TODO: run program via system
    }
}

sub search_form {
    print $q->h2('Search'), "\n";

    print $q->start_form(
        -method=>'POST',
        -action=>$global_config->{$GLOBAL_CGI_URL},
        -enctype=>'multipart/form-data');

    # if admin then list users else current user
    my @users = dir_list($global_config->{$GLOBAL_USER_CONFIGS});
    # TODO: unselect all
    print "User:"; print $q->scrolling_list(
        -name=>$USERS,
        -values=>\@users,
        -multiple=>1), "\n";

#    # TODO: admin controls on user-group
#    my @groups = ("group1");
#    print "user-group"; print $q->scrolling_list($GROUPS, \@groups);

    my @uploads = dir_list($DIR . '/' . $global_config->{$GLOBAL_UPLOAD_CONFIGS});

    print "Assignment:";
    print $q->scrolling_list(
        -name=>$UPLOAD,
        -values=>\@uploads,
        -multiple=>1), "\n"; # TODO: (select some or none)

#    print $q->text(-name=>$START_DATE, {class: 'date'});
#    print $q->text(-name=>$END_DATE, {class: 'date'});

#    print $q->checkbox(-name=>$ONLY_MOST_RECENT, -label=>'Only most recent');

    print $q->submit($ACTION_SEARCH), "\n";
    print $q->end_form();

#    window.addEvent('load', function() {
#        new DatePicker('.demo_vista', { pickerClass: 'datepicker_vista' });

}

sub add_row {
    my ($tree, $val, $depth, @keys) = @_;

    # Check if not a full pattern
    my ($upload, $user, $date, $file) = @keys;
    my @k = ($upload, $user, $date, $file);
    foreach my $i (0..$#k) {
        if (not defined $k[$i] and defined $k[$i+1]) { return ($depth, @keys); }
    }

    @k = grep {defined $_} @k;
    my $key = join(',', @k);
    $tree->{$key} = ("  "x$#k) . $val if $key ne "";

    return ($depth+1, @keys);
}

sub search_results {
    my (%tree, @keys);
    my $depth = 0;

    foreach my $upload (uploads()) {
        my ($depth, @keys) = add_row(\%tree, upload_line($depth, $upload), $depth, @keys, $upload);
        foreach my $user (users($upload)) {
            my ($depth, @keys) = add_row(\%tree, user_line($depth, $user), $depth, @keys, $user);
            foreach my $date (dates($upload, $user)) {
                my ($depth, @keys) = add_row(\%tree, date_line($depth, $date), $depth, @keys,
                               "$date|$user|$upload");
                # NOTE: Dates may not be unique so we add user and upload
                # or "upload/user" or "user/date/upload", i.e., sort by
                foreach my $file (files($upload, $user, $date)) {
                    my ($depth, @keys) = add_row(\%tree, file_line($depth, $file), $depth, @keys, $file);
                }
            }
        }
    }

    print $q->h2("Results"), "\n";
    print $q->start_table({-border=>2}), "\n";
    foreach my $key (sort keys %tree) {
        #print "[", $key, "]\n";
        print $tree{$key}, "\n";
    }
    print $q->end_table(), "\n";
}

#    my $show_empty = $q->param($SHOW_EMPTY);
#    my $show_new_upload = $q->param($SHOW_NEW_UPLOAD);
#    my $show_upload = 1;  # show new (only if upload is first in list)
#    my $show_user = 1; #show empty (only if upload or user)

sub uploads {
    my @c_uploads = dir_list($DIR . "/" . $global_config->{$GLOBAL_UPLOAD_CONFIGS});
    my @q_uploads = param_list($UPLOADS, @c_uploads);
    return intersect(\@q_uploads, \@c_uploads);
}

sub upload_line {
    # TODO: validate link
    my ($depth, $upload) = @_;
    #my ($upload_name, $upload_config) = upload_config($upload);
    my $upload_config = upload_config($upload);
    my $text = "";
    $text .= "\n";
    $text .= $q->Tr($q->td($upload_config->{$UPLOAD_TITLE}) . "\n",
                    $q->td($upload_config->{$UPLOAD_DUE}) . "\n");
    if (1) {
        my $txt2;

        $txt2 .= $q->start_form(
            -method=>'POST',
            -action=>$global_config->{$GLOBAL_CGI_URL},
            -enctype=>'multipart/form-data');
        $txt2 .= $q->hidden(
            -name=>$UPLOAD, -value=>$upload_config->{$UPLOAD_NAME}) . "\n";
# TODO: check about stiky
        # TODO: flag for whether to do upload fields
        for (my $i = 0; $i < $upload_config->{$UPLOAD_FILE_COUNT}; $i++) {
            $txt2 .= $q->filefield(-name=>$FILE) . "\n";
        }
        $txt2 .= $q->checkbox(-name=>$ACTION_VALIDATE, -label=>"Validate")."\n";
        $txt2 .= $q->submit($ACTION_UPLOAD) . "\n";
        $txt2 .= $q->end_form() . "\n";

        $text .= $q->Tr($q->td($upload_config->{$UPLOAD_MESSAGE}) . "\n",
                        $q->td({-colspan=>5}, $txt2));
    }
    return $text;
}

# TODO: select multiple validators

sub users { # TODO: filter by group
    # if not-admin then user=login
    my ($upload) = @_;

    my @c_users = dir_list($global_config->{$GLOBAL_USER_CONFIGS});
    my @q_users = param_list($USERS, @c_users);
    #my @c_groups = (); # TODO
    #my @groups = param_list($GROUPS, @c_groups); # as list? (none -> no filter)
    #my @d_users = dir_list($UPLOAD_DIR . '/' . $upload);
    return intersect(\@q_users, \@c_users);
}

sub user_line {
    my ($depth, $user) = @_;
    return $q->Tr($q->td({-colspan=>$depth}), $q->td($user)); }

sub dates { # TODO: filter by start and end date only most recent
    my ($upload, $user) = @_;

    my @dates = dir_list($global_config->{$GLOBAL_UPLOAD_FILES}, $upload, $user);
    return @dates;

    # TODO
    my $start = $q->param($START_DATE);
    my $end = $q->param($END_DATE);
    if ($#dates == -1) { return "pseudo_date"; }
    else { return @dates; }
}

# TODO: user, author, cells
sub date_line {
    my ($depth, $date) = @_;
    return $q->Tr($q->td({-colspan=>$depth}), $q->td($date)); }

sub files {
    my ($upload, $user, $date) = @_;
    return dir_list($global_config->{$GLOBAL_UPLOAD_FILES},
                    $upload, $user, $date);
}

sub file_line {
    my ($depth, $file) = @_;
    return $q->Tr($q->td({-colspan=>$depth}), $q->td($file), $q->td("modified"));
#                # TODO: is overdue
#                # TODO: zebra stripes
#                print $q->Tr(
#                    $q->td({rowspan=>n}, [$assignment, $user, $date]),
#                    map { $q->td(file); $q->td(size); } @files);
}

################
# Config Files
################

sub user_config {
#    my ($user_name) = @_;
#    return {
#        $USER_NAME => $user_name,
#        $USER_FULL_NAME => full_name,
#    };
#    my $config = read_config($global_config->{$GLOBAL_USER_CONFIGS} . '/' . $user);
#    return $config;

}

sub upload_config {
#    my ($upload_name) = @_;
#    return {
#        $UPLOAD_NAME => $upload_name,
#        $UPLOAD_TITLE => 'title',
#        $UPLOAD_MESSAGE => 'message',
#        $UPLOAD_DUE => 'due',
#        $UPLOAD_FILE_COUNT => '2',
#        file_size => 'file_size',
#        file_regex => 'file_regex',
#        $UPLOAD_VALIDATORS => [['cmd', 'arg1', 'arg1']],
#    };

    my ($upload) = @_;
    return read_config($DIR . '/' . $global_config->{$GLOBAL_UPLOAD_CONFIGS} . '/' . $upload);
    
    # check assignment is valid
    # do upload names need to match? should they be inside?

}

sub safe_param {
    my ($param) = @_;
    my ($result) = $q->param($param) =~ /([A-Za-z0-9]*)/;
    return $result;
}

sub read_config {
    my ($filename) = @_;
    local $/;
    open(my $fh, '<', $filename);
    return decode_json(<$fh>);
}

################
# Utility
################

sub param_list {
    my ($param, @def) = @_;
    my @result = $q->param($param);
    return @result ? @result : @def;
}

sub intersect {
    my ($a, $b) = @_;
    my %a = map {($_,1)} @$a;
    return grep {$a{$_}} @$b;
}

sub start_form {
    my $action = shift;
    print $q->start_form(
        -method=>'POST',
        -action=>$global_config->{$GLOBAL_CGI_URL},
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
    my $dir = join '/', @_;
    my %tree = (
#        'upload_configs' => ['upload1', 'upload2'],
        'user_configs' => ['user1', 'user2', 'user3'],
        'upload_files/upload1/user1' => ['date1', 'date2'],
        'upload_files/upload1/user2' => ['date1', 'date2'],
        'upload_files/upload1/user3' => [],
        'upload_files/upload2/user1' => ['date1', 'date2'],
        'upload_files/upload2/user2' => ['date1', 'date2'],
        'upload_files/upload2/user3' => [],

        'upload_files/upload1/user1/date1' => ['file1', 'file2'],
        'upload_files/upload1/user1/date2' => ['file1', 'file2'],
        'upload_files/upload1/user2/date1' => ['file1', 'file2'],
        'upload_files/upload1/user2/date2' => ['file1', 'file2'],
        'upload_files/upload2/user1/date1' => ['file1', 'file2'],
        'upload_files/upload2/user1/date2' => ['file1', 'file2'],
        'upload_files/upload2/user2/date1' => ['file1', 'file2'],
        'upload_files/upload2/user2/date2' => ['file1', 'file2'],
        );
#    print join ".", @_ if not defined $tree{$dir};
    return @{$tree{$dir}} if exists $tree{$dir};

    my $d = DirHandle->new($dir);
    if (defined $d) {
        my @ds = $d->read;
        $d->close;
        @ds = grep {!/^\./} @ds; # skip dot files
        @ds = grep {!/~$/} @ds; # skip backup files
        return sort @ds;
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
    print "mkdir $dir\n";
    if (mkdir $dir) { return $dir; }
    return 0;
}
