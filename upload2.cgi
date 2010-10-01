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
my $START_DATE="start";
my $END_DATE="end"; # includes "last"
my $SHOW_EMPTY="show_empty";
my $SHOW_NEW_UPLOAD="show_new_upload";
my $ONLY_MOST_RECENT="only_most_recent";

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

my $USER_NAME = 'user_name';
my $USER_FULL_NAME = 'full_name';

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
    if (defined $q->param($ACTION_SEARCH_UPLOADS)) { upload_results(); }
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

sub filename_param {
    my $p = $q->param($_[0]);
    return $p unless defined $p;
    my ($v) = $p =~ /([A-Za-z0-9]*)/;
    return $v;
}

sub validate {
    print $q->h2('Validation'), "\n";
    my ($upload, $user, $date) = map {filename_param $_} ($UPLOAD, $USER, $DATE);
    # TODO: filter $date by "last"
    # TODO: check that exists and have permissions

    my $upload_config = upload_config($upload);
    foreach my $validator (@{$upload_config->{$UPLOAD_VALIDATORS}}) {
        $ENV{PATH} = '/usr/bin'; #TODO: from config
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
    print $q->Tr(map {$q->td($_)}
                 ("User", "Assignment", "Date"));
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
    print $q->end_form();

#    window.addEvent('load', function() {
#        new DatePicker('.demo_vista', { pickerClass: 'datepicker_vista' });

}

sub add_row {
    my ($tree, $val, $depth, @keys) = @_;

    # Check if not a full pattern
    my ($upload, $user, $date, $file) = @keys;
#    my @k = ($date, $file);
    my @k = ($upload, $user, $date, $file);
#    my @k = ($user, $upload, $date, $file);
#    my @k = ($file);
    foreach my $i (0..$#k) {
        if (not defined $k[0] or
            not defined $k[$i] and defined $k[$i+1]) { return ($depth, @keys); }
    }

    @k = grep {defined $_} @k;
    my $key = join(',', @k);
    $tree->{$key} = ("  "x$#k) . $val if $key ne "";

    return ($depth+1, @keys);
}

sub upload_results {
    print $q->h2("Uploads"), "\n";
    print $q->start_table({-border=>2}), "\n";
#    print $q->colgroup({-span=>$columns, -width=>"50"}), "\n";
    foreach my $upload (uploads()) {
#        print "DOWNLOAD: $upload\n";
#
        my $upload_config = upload_config($upload);
        print $q->h3($upload_config->{$UPLOAD_NAME} . ":",
                     $upload_config->{$UPLOAD_TITLE},
                     " (due $upload_config->{$UPLOAD_DUE})"), "\n";
#        "\n";
#        print $q->p("Due $upload_config->{$UPLOAD_DUE}"), "\n";
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
#
#        $text .= nested_row($depth+1,
#                     $q->td({-colspan=>0}, $upload_config->{$UPLOAD_MESSAGE}));
#        $text .= nested_row($depth+1, $q->td({-colspan=>0}, $txt2));
#    }
#

    }
    print $q->end_table(), "\n";
}

sub search_results {
    my (%tree, @keys);
    my $depth = 0;
    my $columns;

    foreach my $upload (uploads()) {
        my ($depth, @keys) = add_row(
            \%tree, upload_line($depth, $upload), $depth, @keys, $upload);
        foreach my $user (users($upload)) {
            my ($depth, @keys) = add_row(
                \%tree, user_line($depth, $upload, $user), $depth, @keys, $user);
            foreach my $date (dates($upload, $user)) {
                my ($depth, @keys) = add_row(
                    \%tree, date_line($depth, $upload, $user, $date),
                    $depth, @keys, "$date|$user|$upload");
                # NOTE: Dates may not be unique so we add user and upload
                # or "upload/user" or "user/date/upload", i.e., sort by
                foreach my $file (files($upload, $user, $date)) {
                    $columns = $depth;
                    my ($depth, @keys) = add_row(
                        \%tree, file_line($depth, $upload, $user, $date, $file),
                        $depth, @keys, "$date|$user|$upload|$file");
                }
            }
        }
    }

    print $q->h2("Results"), "\n";
    print $q->start_table({-border=>2}), "\n";
    print $q->colgroup({-span=>$columns, -width=>"50"}), "\n";

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

sub uniq_by {
    my ($fun, @xs) = @_;
    my %ht;
    foreach my $i (@xs) { $ht{&$fun($i)} = $i; }
    return values %ht;
}

sub uniq { return keys %{{ map { $_ => $_ } @_ }}; }

#sub search_results2 {
#    my @rows = map {
#        my $upload = $_;
#        map {
#            my $user = $_;
#            map {
#                my $date = $_;
#                map {
#                    my $file = $_;
#                    {upload => $upload, user => $user,
#                     date => $date, file => $file}
#                } files($upload, $user, $date)
#            } dates($upload, $user)
#        } users ($upload)
#    } uploads();
#
#    for my $depth (0..$#group_by) {
#        my @fields = @group_by[0..$depth];
#        my @headers = uniq_by \@fields @rows;
#        foreach my $header (@headers) {
#            if ($fields[$depth] eq 'upload')upload_line(\%rows, $depth, $header);
#            if ($fields[$depth] eq 'users') users_line(\%rows, $depth, $header);
#
#        }
#    }
#
##    add file lines;
#
##    print all with ordering;
#
#}

sub uploads {
    my @c_uploads = dir_list($global_config->{$GLOBAL_UPLOAD_CONFIGS});
    my @q_uploads = param_list($UPLOADS, @c_uploads);
    return intersect(\@q_uploads, \@c_uploads);
}

sub nested_row {
    my ($depth, @text) = @_;
    return $q->Tr($depth ? $q->td({-colspan=>$depth}) . "\n" : "",
                  map {$_."\n"} @text);
}

sub upload_line {
    # TODO: validate link
    my ($depth, $upload) = @_;
    #my ($upload_name, $upload_config) = upload_config($upload);
    my $upload_config = upload_config($upload);
    my $text = "\n";
    $text .= nested_row($depth,
                        $q->td({-colspan=>0},
                               $upload_config->{$UPLOAD_TITLE},
                               " (due $upload_config->{$UPLOAD_DUE})"));
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

# TODO: sort by fullname vs by username

sub user_line {
    my ($depth, $upload, $user) = @_;
    my $user_config = user_config($user);
    return nested_row(
        $depth, $q->td(
            {-colspan=>0},
            $user_config->{$USER_NAME},
            " ($user_config->{$USER_FULL_NAME})"));
}

sub dates { # TODO: filter by start and end date only most recent
    my ($upload, $user) = @_;

    my @dates =
        dir_list($global_config->{$GLOBAL_UPLOAD_FILES}, $upload, $user);

    if ($#dates != -1 and $q->param($ONLY_MOST_RECENT)) {
        @dates = ($dates[$#dates]);
    }
    
    return @dates;

    # TODO
    my $start = $q->param($START_DATE);
    my $end = $q->param($END_DATE);
    if ($#dates == -1) { return "pseudo_date"; }
    else { return @dates; }
}

# TODO: user, author, cells
sub date_line {
    my ($depth, $upload, $user, $date) = @_;
    return nested_row(
        $depth,
        $q->td({-colspan=>0},
               # TODO: encode $upload, $user, $date
               $date,
               form_link("(revalidate)",
                         $ACTION_VALIDATE, $ACTION_VALIDATE,
                         $UPLOAD, $upload, $USER, $user, $DATE, $date)));
#                # TODO: is overdue
#                # TODO: zebra stripes
#                print $q->Tr(
#                    $q->td({rowspan=>n}, [$assignment, $user, $date]),
#                    map { $q->td(file); $q->td(size); } @files);
}

sub files {
    my ($upload, $user, $date) = @_;
    return dir_list($global_config->{$GLOBAL_UPLOAD_FILES},
                    $upload, $user, $date);
}

sub file_line {
    my ($depth, $upload, $user, $date, $file) = @_;
    my $filename = "$DIR/$global_config->{$GLOBAL_UPLOAD_FILES}/" .
        "$upload/$user/$date/$file";
    return nested_row($depth,
                      $q->td(
                          form_link($file,
                                    $ACTION_DOWNLOAD, $ACTION_DOWNLOAD,
                                    $UPLOAD, $upload,
                                    $USER, $user,
                                    $DATE, $date)),
                      $q->td({-align=>'right'}, -s $filename, " bytes"));
}

sub form_link {
    my ($text, %params) = @_;
    my $href = "$global_config->{$GLOBAL_CGI_URL}?" .
        join("&", map {$_ . "=" . $q->escape($params{$_})} keys %params);
#        "?$UPLOAD=$upload&$USER=$user&$DATE=&date"},
    return $q->a({-href=>$href}, $text);
}


################
# Config Files
################

# TODO: cache configs

sub user_config {
    my ($user) = @_;
    my $config = read_config($global_config->{$GLOBAL_USER_CONFIGS},
                             $user);
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

sub safe_param {
    my ($param) = @_;
    my ($result) = $q->param($param) =~ /([A-Za-z0-9]*)/;
    return $result;
}

sub read_config {
    my $filename = join '/', $DIR, @_;
    local $/;
    open(my $fh, '<', $filename) or print "No file $filename\n"; # TODO
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
    return $q->start_form(
        -method=>'POST',
        -action=>$global_config->{$GLOBAL_CGI_URL},
        -enctype=>'multipart/form-data');
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
