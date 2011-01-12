#! /usr/bin/perl -T
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout
umask 0077; # Default to private files

# Modules from Core
use CGI qw/-private_tempfiles -nosticky/;
use Class::Struct;
use File::Basename;
use File::Copy; # copy() but move() has tainting issues
use File::Path qw/mkpath/;
use DirHandle;
use Memoize; memoize('read_config');

# Modules not from Core
use JSON;
use Date::Manip;

# Future features:
# * Critical
#  - file_name regex (as validator)
#  - config file validator
#  - active vs. non-active folders
#  - Admin interface (but be clear what it looks like to student)
#
#  - Report back search params
#  - text/plain on file download (regex)
#  - config "Select" and "Folder" text
# * Non-critical
#  - Server Time offset
#  - Change "folder" to "assignment"
#  - Change "browse" to "select"(?)
#  - Print server time on pages
#  - hilight "overdue" in red or bold
#  - Upload chmod for group?
#  - HTML formatting / CSS classes
#  - Download tar-ball.
#  - Use path_info() to dispatch upload, download and pre-upload(?)
#  - Full URL to cgi.cs.indiana.edu? url()
#  - struct for checker names?
#  - Folder edit: link under browse?, new (link under browse), delete, active, rename, validate config
#  - Hilight sorted column
#  - file size with commas
#
#  - List of testing people
#  - Put "multiselect" under Users and Folders search box
# * Considering not adding
#  - highlight incomplete submissions
#  - Upload page? (link under browse)
#  - Check box for show upload form
# * Seriously Considering not adding
#  - select subset of checkers to run
#  - detailed sort-by
#  - Separate upload page (so full assignment can be listed)

# NOTES:
#  - uploading multiple file w/ same name clobbers older files
#  - if you want to validate filenames, write an external checker
#  - group work is possible if you symlink the right assignment folders together

# File Paths
use constant DIR => "/u-/adamsmd/projects/upload/demo";
#use constant DIR => "demo";
use constant GLOBAL_CONFIG_FILE => "global_config.json";

# CGI Constants
use constant {
    HEADER_OCTET_STREAM => 'application/octet-stream', HTTP_SEE_OTHER => 303,
    DO_DOWNLOAD => "download", DO_UPLOAD => "upload",
    DO_SEARCH => "search", DO_RESULTS => "results",
    USERS => "users", FOLDERS => "folders",
    START_DATE => "start_date", END_DATE => "end_date",
    ONLY_LATEST => "only_latest", CHECK_FOLDERS => "check_folders",
    DUE => 'due', DUE_PAST => 'past', DUE_FUTURE => 'future',
    SUBMITTED => 'submitted', SUBMITTED_YES => 'yes', SUBMITTED_NO => 'no',
    SORTING => 'sorting',
    SORTING_FOLDER => 'folder', SORTING_USER => 'user', SORTING_DATE => 'date',
    FILE => 'file',
    NAVBAR => 'navbar', SEARCH => 'search', RESULTS => 'results',
    FOLDER => 'folder', BODY => 'body' };
use constant { CSS => <<'EOT' };
th { vertical-align:top; text-align:left; }
td { vertical-align:top; }
h2 { border-bottom:2px solid black; }
.navbar > h3:first-child { margin-top:0; } /* Stop spurious margin */
.navbar { padding:0.3em; width:20em;float:left;border:solid black 1px; }
.search tr td * { width:100%; }
.results { width:100%;border-collapse: collapse; }
.results thead { border-bottom:2px solid black; }
.results tbody { border-bottom:1px solid black; }
.results tbody tr:first-child td+td+td+td+td+td+td+td { text-align:right; }
.results tbody tr+tr td+td { text-align:right; }
.results tbody tr+tr td+td[colspan] { text-align:left; }
.results tbody tr td[colspan="1"]+td { background:#EEE; }
.folder { width:100%; border-bottom:1px solid black; }
.body { margin-left:22em; }
#.graybg { background:#EEE; }
EOT

# String formats
sub trusted ($) { ($_[0] =~ /^(.*)$/s)[0]; }
sub date ($) { ((UnixDate($_[0], "%O") or "") =~ /^([A-Za-z0-9:-]+)$/)[0]; }
sub file ($) { (($_[0] or "") =~ qr/^(?:.*\/)?([A-Za-z0-9_\. -]+)$/)[0]; }

# Structs
struct(GlobalConfig=>[title=>'$', folder_configs=>'$', folder_files=>'$',
                      cgi_url=>'$', path=>'$', # Env PATH for checkers
                      post_max=>'$', admins=>'*@', users=>'*%']);
struct(UserConfig=>[name => '$', full_name => '$', expires => '$']);
struct(FolderConfig=>[name=>'$', title=>'$', text=>'$', due=>'$',
                      file_count=>'$', checkers=>'@']);
struct(Row=>[folder=>'FolderConfig',user=>'UserConfig',date=>'$',files=>'@']);

################
# Setup
################

my $global_config = GlobalConfig->new(read_config(GLOBAL_CONFIG_FILE));
$CGI::POST_MAX = $global_config->post_max;
($ENV{PATH}) = $global_config->path;

my $q = CGI->new;
my $error = $q->cgi_error();
die $error if $error;

################
# Inputs
################

# Dates
my $start_date = date $q->param(START_DATE);
my $end_date = date $q->param(END_DATE);
my $now = date "now";

# Flags
my $only_latest = $q->param(ONLY_LATEST) ? 1 : 0;
my $check_folder = $q->param(CHECK_FOLDERS) ? 1 : 0;

# Semi-flags
my $submitted_yes = member(SUBMITTED_YES, 1, $q->param(SUBMITTED));
my $submitted_no = member(SUBMITTED_NO, 1, $q->param(SUBMITTED));
my $due_past = member(DUE_PAST, 1, $q->param(DUE));
my $due_future = member(DUE_FUTURE, 1, $q->param(DUE));

my ($sorting) = ($q->param(SORTING) or "") =~ /^([A-Za-z0-9_]*)$/;

# Directories
my $folder_configs = file $global_config->folder_configs;
my $folder_files = file $global_config->folder_files;

# User
my $remote_user = file $q->remote_user();
$remote_user="user1";
my $is_admin = member($remote_user, 0, @{$global_config->admins});
my @all_users = sort keys %{$global_config->users};
@all_users = sort (intersect(\@all_users, [$remote_user])) unless $is_admin;
my @users = $q->param(USERS) ? $q->param(USERS) : @all_users;
@users = sort map { file $_ } @users;
@users = sort (intersect(\@all_users, \@users));

# Download file
my $file = file $q->param(FILE);

# Folders
my @all_folders = dir_list($global_config->folder_configs);
my @folders = map { file $_ } $q->param(FOLDERS);
@folders = sort (intersect(\@all_folders, \@folders));
@folders = map { $_->name }
    grep { $due_past and $_->due le $now or $due_future and $_->due gt $now}
    list_folders(@folders);

# Other inputs
#  param: DO_*
#  upload: UPLOAD_FILE
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

sub say { print @_, "\n"; } # Emulate Perl 5.10 feature

error("No such user: $remote_user")
    unless exists $global_config->users->{$remote_user};
error("Access for '$remote_user' expired as of ", user($remote_user)->expires)
    unless $now lt date(user($remote_user)->expires);

if ($q->param(DO_DOWNLOAD)) { download(); }
elsif ($q->param(DO_UPLOAD)) { upload(); }
else {
    print $q->header();
    say $q->start_html(-title=>$global_config->title,
                           -style=>{-verbatim=>CSS});
    say $q->h1($global_config->title);

    say $q->start_div({-class=>NAVBAR});
    browse_folders();
    say $q->h3("... or",
                   $q->a({-href=>form_url(DO_SEARCH, 1)}, "Search"));
    search_form() if $q->param(DO_SEARCH);
    say $q->end_div();

    if ($q->param(DO_RESULTS)) {
        say $q->start_div({-class=>BODY});
        folder_results();
        search_results();
        say $q->end_div();
    }

    say $q->end_html();
}
exit 0;

################
# Actions
################

sub error {
    print $q->header();
    say $q->start_html(-title=>$global_config->title);
    say $q->h1($global_config->title . ": Error");
    my ($package, $filename, $line) = caller;
    say $q->p(join "", @_, " (At line $line.)");
    say $q->p("Go back and try again.");
    exit 0;
}

sub download {
    my $folder = $folders[0] or error "No folder selected.";
    my $user = $users[0] or error "No user selected.";
    my $filename = filename($folder,$user,$start_date,$file);
    -f $filename and -r $filename or
        error "Can't read '$folder,$user,$start_date,$file'";
    print $q->header(-type=>HEADER_OCTET_STREAM,
                     -attachment=>$file, -Content_length=>-s $filename);
    copy($filename, *STDOUT) or die; # TODO: error message
}

sub upload {
    $q->upload(FILE) or error "No files selected for upload.";
    my $folder = $folders[0] or error "No folder selected for upload.";
    my %names;
    foreach my $name (map { file $_ } $q->upload(FILE)) {
        error "Duplicate file name: '$name'" if $names{$name};
        $names{$name} = 1;
    }

    my $target_dir = filename($folder,$remote_user,$now);
    mkpath($target_dir) or
        error "Can't create folder '$folder,$remote_user,$now' for upload: $!";
    foreach my $file ($q->upload(FILE)) {
        my $name = file $file;
        copy($file, "$target_dir/$name") or
            error "Can't store file '$folder,$remote_user,$now,$name'",
                  " for upload: $!";
    }
    print $q->redirect(-uri=>form_url(CHECK_FOLDERS, $q->param(CHECK_FOLDERS),
                                      FOLDERS, $folder, USERS, $remote_user,
                                      START_DATE, $now, END_DATE, $now,
                                      DO_RESULTS, 1),
                       -status=>HTTP_SEE_OTHER);
}

sub browse_folders {
    # Print
    say $q->h3("Select Folder");
    say $q->start_table();
    foreach my $folder (list_folders(@all_folders)) {
        say $q->Tr($q->td({colspan=>2},
                          $q->a({-href=>form_url(
                                      FOLDERS, $folder->name, DO_RESULTS, 1)},
                                $folder->name . ":", $folder->title)));
        my $submitted = grep { list_dates($folder->name, $_) } @all_users;
        my $num_users = @all_users;
        say row(
            $q->small("&nbsp;&nbsp;Due " . $folder->due),
            $q->small($submitted ?
                      (" - Submitted" .
                       ($is_admin ? " ($submitted/$num_users)" : "")) :
                      ($now ge $folder->due ? " - Overdue" : "")));
    }
    say $q->end_table();
}

sub search_form {
    # Print
    say $q->start_form(-action=>$global_config->cgi_url, -method=>'GET');
    say $q->start_table({-class=>SEARCH});
    rows(["User:", $q->scrolling_list(
              -name=>USERS, -multiple=>1, -size=>3,
              -values=>\@all_users, -default=>\@all_users)],
         ["Folder:", $q->scrolling_list(
              -name=>FOLDERS, -multiple=>1, -size=>3,
              -values=>\@all_folders, -default=>\@all_folders)],
         ["Start date: ", $q->textfield(-name=>START_DATE, -value=>'Any')],
         ["End date: ", $q->textfield(-name=>END_DATE, -value=>'Any')],
         ["Only latest:", $q->checkbox(-name=>ONLY_LATEST, -label=>'')],
         ["Run checks:", $q->checkbox(-name=>CHECK_FOLDERS, -label=>'')],
         ["Status:", multiple_list(SUBMITTED,
                                   SUBMITTED_YES, "Submitted",
                                   SUBMITTED_NO, "Not Submitted")],
         ["Due:", multiple_list(DUE, DUE_PAST, "Past", DUE_FUTURE, "Future")],
         ["Sort by: ", scrolling_list(SORTING, 1, [],
                                      SORTING_FOLDER, "Folder",
                                      SORTING_USER, "User",
                                      SORTING_DATE, "Date")],
         ["", $q->submit(-value=>"Search")]);
    say $q->end_table();
    say $q->hidden(-name=>DO_SEARCH, -default=>1);
    say $q->hidden(-name=>DO_RESULTS, -default=>1);
    say $q->end_form();
}

sub search_results {
    # Search
    my @rows;
    foreach my $folder (list_folders(@folders)) {
        foreach my $user (list_users($folder->name)) {
            my @dates = list_dates($folder->name, $user->name);
            if (@dates) {
                if ($submitted_yes) {
                    foreach my $date (@dates) {
                        push @rows, Row->new(
                            folder=>$folder, user=>$user, date=>$date,
                            files=>[dir_list($folder_files, $folder->name,
                                             $user->name, $date)]);
                    }
                }
            } else {
                push @rows, Row->new(folder=>$folder, user=>$user, date=>'',
                                     files=>[]) if $submitted_no;
            }
        }
    }
    @rows = sort {
        ($sorting eq SORTING_USER and $a->user->name cmp $b->user->name) or
            ($sorting eq SORTING_DATE and $a->date cmp $b->date) or
            ($a->folder->name cmp $b->folder->name) or
            ($a->user->name cmp $b->user->name) or
            ($a->date cmp $b->date)} @rows;

    # Print and run checks
    say $q->h2("Previously uploaded files");
    # NOTE: Perl Idiom: @{[expr]} interpolates an arbitrary expr into a string
    say $q->start_table({-class=>RESULTS});
    say $q->thead($q->Tr($q->th(['Folder','Title','User','Name','Date',
                                 'Check', 'Files','Size (bytes)'])));
    if (not @rows) {
        say "<tr><td colspan=8><center>No results to display. 
                 Browse or search to select folders.</center></td></tr>";
    } else {
        foreach my $row (@rows) {
            say "<tbody>";
            my @file_rows = (not @{$row->files}) ?
                (["(No files)", ""]) :
                map { my $link = row_url($row, DO_DOWNLOAD, 1, FILE, $_);
                      my $size = -s filename(
                          $row->folder->name, $row->user->name, $row->date, $_);
                      ["<a href='$link'>$_</a>", $size];
            } @{$row->files};
            my $link = row_url($row, CHECK_FOLDERS, 1, DO_RESULTS, 1);
            say mrow([$row->folder->name, $row->folder->title,
                      $row->user->name, $row->user->full_name,
                      ($row->date ? ($row->date,"<a href='$link'>[check]</a>")
                       : ("(No uploads)", ""))], @file_rows);

            if ($check_folder and $row->date) {
                my $len = @{$row->folder->checkers};
                my $passed = index_grep(
                    sub { my ($num, $checker) = @_;
                          say indentrow(1, 8, "Running @{[$checker->[0]]} 
                                               (check $num of $len)");
                          say start_indentrow(2, 8), $q->start_div();
                          system @{$checker->[1]}, filename(
                              $row->folder->name, $row->user->name, $row->date);
                          die $! if $? == -1;
                          say $q->end_div(), end_indentrow();
                          say indentrow(2, 8, $? ? 'Failed' : 'Passed');
                          $? }, @{$row->folder->checkers});
                say indentrow(1, 8, "Passed $passed of $len checks");
            }
            say "</tbody>";
        }
    }
    say $q->end_table();
}

sub folder_results {
    # Search
    my @folders = list_folders(@folders);

    # Print
    say $q->h2("Upload new files");
    say "<center>No results to display. ",
            "Browse or search to select folders.</center>" unless @folders;
    foreach my $folder (@folders) {
        say $q->start_div({-class=>FOLDER});
        say $q->h3($folder->title,"(".$folder->name.") - due",$folder->due);
        say $q->div($folder->text);

        say $q->start_form(-method=>'POST', -enctype=>&CGI::MULTIPART,
                               -action=>$global_config->cgi_url);
        say $q->hidden(-name=>FOLDERS, -value=>$folder->name, -override=>1);
        say $q->hidden(-name=>CHECK_FOLDERS, -value=>1, -override=>1);
        for my $i (1..$folder->file_count) {
            say $q->p("File $i:", $q->filefield(-name=>FILE, -override=>1));
        }
        say $q->p($q->submit(DO_UPLOAD, "Upload files"));
        say $q->end_form();
        say $q->end_div();
    }
}

################
# Listings
################

sub folder {
    FolderConfig->new(name => $_[0], read_config($folder_configs, $_[0])) }
sub list_folders { map { folder $_ } @_; }
sub user { UserConfig->new(name => $_[0], %{$global_config->users->{$_[0]}}) }
sub list_users { map { user $_ } @users; }
sub list_dates {
    my ($folder, $user) = @_;
    my @dates = dir_list($folder_files, $folder, $user);
    @dates = map { date $_ } @dates;
    @dates = grep { -d filename($folder, $user, $_) } @dates;
    @dates = grep {$start_date le $_} @dates if $start_date;
    @dates = grep {$end_date ge $_} @dates if $end_date;
    @dates = ($dates[$#dates]) if $#dates != -1 and $only_latest;    
    return @dates;
}
sub filename { join('/', DIR, $folder_files, @_); }

################
# CGI Utility
################

# Expects: ($key1, $val1, $key2, $val2)
# Returns: $cgi_url?$key1&$val1&$key2&val2
sub form_url {
    my %args = @_;
    return $global_config->cgi_url . "?" .
        join "&", map { $_ . "=" . $args{$_} } keys %args;
}

sub row_url {
    form_url(FOLDERS, $_[0]->folder->name, USERS, $_[0]->user->name,
             START_DATE, $_[0]->date, END_DATE, $_[0]->date, @_);
}

# Expects: (name, key, label, key, label)
sub multiple_list {
    my ($name, %args) = @_;
    return scrolling_list($name, 1, [keys %args], %args);
}

sub scrolling_list {
    my ($name, $multiple, $default, %args) = @_;
    return $q->scrolling_list(
        -name=>$name, -multiple=>$multiple,
        -values => [keys %args], -default => $default, -labels => \%args);
}

sub row { return $q->Tr($q->td([@_])); }
sub rows { $q->start_table(); map { say row(@$_) } @_; }

sub indentrow {
    my ($indent, $length, $data) = @_;
    start_indentrow($indent, $length) . $data . end_indentrow();
}

sub start_indentrow {
    my ($indent, $length) = @_;
    "<tr><td colspan=$indent></td><td colspan=@{[$length-$indent]}>";
}
sub end_indentrow { "</td></tr>" }

sub mrow {
    my ($prefix, @rows) = @_;
    return "<tr>" . $q->td({-rowspan=>scalar(@rows)}, $prefix) .
        join("</tr><tr>", (map { $q->td($_) } @rows)) . "</tr>";
}

################
# General Util
################

sub member {
    my ($value, $default, @list) = @_;
    return $default unless @list;
    return (grep { $_ eq $value } @list) ? 1 : 0;
}

sub index_grep {
    my ($num, $true, $fun, @items) = (0, 0, @_);
    foreach my $item (@items) { $num++; &$fun($num, $item); }
}

sub read_config {
    local $/;
    open(my $fh, '<', join('/', DIR, @_)) or die $!; # TODO: error msg
    my $obj = decode_json(trusted <$fh>);
    return %$obj;
}

sub intersect {
    my ($a, $b) = @_;
    my %a = map {($_,1)} @$a;
    return grep {$a{$_}} @$b;
}

sub dir_list {
    my $d = DirHandle->new(join '/', DIR, @_);
    my @ds = $d ? $d->read : ();
    $d->close if $d;
    @ds = grep {!/^\./} @ds; # skip dot files
    @ds = grep {!/~$/} @ds; # skip backup files
    return sort @ds;
}
