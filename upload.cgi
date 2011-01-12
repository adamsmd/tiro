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
sub say { print @_, "\n"; } # Emulate Perl 5.10 feature

# Modules not from Core
use JSON;
use Date::Manip;
use List::MoreUtils qw/pairwise true uniq/;

################
# Static Definitions
################

# File Paths
use constant DIR => "/u-/adamsmd/projects/upload/demo"; # Root of all paths
use constant GLOBAL_CONFIG_FILE => "global_config.json";

# CGI Constants
use constant {
    HEADER_OCTET_STREAM => 'application/octet-stream', HTTP_SEE_OTHER => 303,
    DO_DOWNLOAD => "download", DO_UPLOAD => "upload",
    DO_SEARCH => "search", DO_RESULTS => "results",
    NO_RESULTS => 'No results to display. Browse or search to select folders.',
    USERS => "users", FOLDERS => "folders",
    START_DATE => "start_date", END_DATE => "end_date",
    ONLY_LATEST => "only_latest", DO_CHECKS => "do_checks",
    DUE => 'due', DUE_PAST => 'past', DUE_FUTURE => 'future',
    SUBMITTED => 'submitted', SUBMITTED_YES => 'yes', SUBMITTED_NO => 'no',
    SORT=>'sort', SORT_FOLDER=>'folder', SORT_USER=>'user', SORT_DATE=>'date',
    FILE => 'file',
    NAVBAR => 'navbar', SEARCH => 'search', RESULTS => 'results',
    FOLDER => 'folder', BODY => 'body' };
use constant { CSS => <<'EOT' };
th { vertical-align:top; text-align:left; }
td { vertical-align:top; }
h2 { border-bottom:2px solid black; }
.navbar > h3:first-child { margin-top:0; } /* Stop spurious margin */
.navbar { padding:0.3em; width:20em;float:left;border:solid black 1px; }
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

# Structs
struct(GlobalConfig=>[title=>'$', folder_configs=>'$', folder_files=>'$',
                      cgi_url=>'$', path=>'$', # Env PATH for checkers
                      post_max=>'$', admins=>'*@', users=>'*%']);
struct(UserConfig=>[name => '$', full_name => '$', expires => '$']);
struct(FolderConfig=>[name=>'$', title=>'$', text=>'$', due=>'$',
                      file_count=>'$', checkers=>'@']);
struct(Row=>[folder=>'FolderConfig',user=>'UserConfig',date=>'$',files=>'@']);

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

# Dates
my $start_date = date $q->param(START_DATE);
my $end_date = date $q->param(END_DATE);
my $now = date "now";

# Flags
my $only_latest = $q->param(ONLY_LATEST) ? 1 : 0;
my $do_checks = $q->param(DO_CHECKS) ? 1 : 0;

# Non-flag options
my $submitted_yes = member(SUBMITTED_YES, 1, $q->param(SUBMITTED));
my $submitted_no = member(SUBMITTED_NO, 1, $q->param(SUBMITTED));
my $due_past = member(DUE_PAST, 1, $q->param(DUE));
my $due_future = member(DUE_FUTURE, 1, $q->param(DUE));

my ($sort) = ($q->param(SORT) or "") =~ /^([A-Za-z0-9_]*)$/;

# Directories
my $folder_configs = file $global_config->folder_configs;
my $folder_files = file $global_config->folder_files;

# Users
my $remote_user = file $q->remote_user();
$remote_user="user1"; # HACK
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
# Main Code
################

error("No such user: $remote_user")
    unless exists $global_config->users->{$remote_user};
error("Access for $remote_user expired as of ", user($remote_user)->expires)
    unless $now lt date(user($remote_user)->expires);

if ($q->param(DO_DOWNLOAD)) { download(); }
elsif ($q->param(DO_UPLOAD)) { upload(); }
else {
    print $q->header();
    say $q->start_html(-title=>$global_config->title,
                           -style=>{-verbatim=>CSS});
    say $q->h1($global_config->title);

    say $q->start_div({-class=>NAVBAR});
    say $q->h3("Select Folder");
    browse_folders();
    say $q->h3("... or", href(form_url(DO_SEARCH, 1), "Search"));
    search_form() if $q->param(DO_SEARCH);
    say $q->end_div();

    if ($q->param(DO_RESULTS)) {
        say $q->start_div({-class=>BODY});
        say $q->h2("Upload new files");
        folder_results();
        say $q->h2("Previously uploaded files");
        search_results();
        say $q->end_div();
    }

    say $q->end_html();
}
exit 0;

################
# Actions
################

sub download {
    my ($folder, $user) = ($folders[0], $users[0]);
    my $path = filename($folder,$user,$start_date,$file);
    $folder and $user and $start_date and $file and -f $path and -r $path or
        error("Can't read '$folder,$user,$start_date,$file'");
    print $q->header(-type=>HEADER_OCTET_STREAM,
                     -attachment=>$file, -Content_length=>-s $path);
    copy($path, *STDOUT) or die $!;
}

sub upload {
    $q->upload(FILE) or error("No files selected for upload.");
    $q->upload(FILE) == uniq map { file $_ } $q->upload(FILE) or
        error("Duplicate file names.");
    my $folder = $folders[0] or error("No folder selected for upload.");

    my $target_dir = filename($folder,$remote_user,$now);
    mkpath($target_dir) or error("Can't create: $folder,$remote_user,$now: $!");
    foreach my $file ($q->upload(FILE)) {
        my $name = file $file;
        copy($file, "$target_dir/$name") or
            error("Can't save file '$folder,$remote_user,$now,$name': $!");
    }
    print $q->redirect(
        -status=>HTTP_SEE_OTHER,
        -uri=>form_url(DO_RESULTS, 1, DO_CHECKS, $do_checks,
                       FOLDERS, $folder, USERS, $remote_user, START_DATE, $now,
                       END_DATE, $now));
}

sub browse_folders {
    say $q->start_table();
    foreach my $folder (list_folders(@all_folders)) {
        say row_span(2, href(form_url(DO_RESULTS, 1, FOLDERS, $folder->name),
                             $folder->name . ":", $folder->title));
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
         ["Run checks:", $q->checkbox(-name=>DO_CHECKS, -label=>'')],
         ["Status:", multiple_list(SUBMITTED,
                                   SUBMITTED_YES, "Submitted",
                                   SUBMITTED_NO, "Not Submitted")],
         ["Due:", multiple_list(DUE, DUE_PAST, "Past", DUE_FUTURE, "Future")],
         ["Sort by: ", scrolling_list(
              SORT, 1, [SORT_FOLDER],
              SORT_FOLDER, "Folder", SORT_USER, "User", SORT_DATE, "Date")],
         ["", $q->submit(-value=>"Search")]);
    say $q->end_table();
    say $q->hidden(-name=>DO_SEARCH, -default=>1);
    say $q->hidden(-name=>DO_RESULTS, -default=>1);
    say $q->end_form();
}

sub search_results {
    ### Search
    my @rows;
    foreach my $folder (list_folders(@folders)) {
        foreach my $user (list_users($folder->name)) {
            my @dates = list_dates($folder->name, $user->name);
            push @rows, Row->new(folder=>$folder, user=>$user, date=>'',
                                 files=>[]) if $submitted_no and not @dates;
            foreach my $date (@dates) {
                push @rows, Row->new(
                    folder=>$folder, user=>$user, date=>$date,
                    files=>[dir_list($folder_files, $folder->name,
                                     $user->name, $date)]) if ($submitted_yes);
            }
        }
    }
    ### Sort
    @rows = sort {($sort eq SORT_USER and $a->user->name cmp $b->user->name) or
                      ($sort eq SORT_DATE and $a->date cmp $b->date) or
                      ($a->folder->name cmp $b->folder->name) or
                      ($a->user->name cmp $b->user->name) or
                      ($a->date cmp $b->date) } @rows;

    ### Print and run checks
    say $q->start_table({-class=>RESULTS});
    say $q->thead($q->Tr($q->th(['Folder','Title','User','Name','Date',
                                 'Check', 'Files','Size (bytes)'])));
    if (not @rows) { say row_span(8, $q->center(NO_RESULTS)); }
    else {
        # NOTE: Perl Idiom: @{[expr]} --> interpolate expr into a string
        foreach my $row (@rows) {
            say $q->start_tbody();
            my @file_rows = @{$row->files} ?
                map { [href(row_url($row, DO_DOWNLOAD, 1, FILE, $_), $_),
                       -s filename($row->folder->name, $row->user->name,
                                   $row->date, $_)];
                    } @{$row->files} : ["(No files)", ""];
            my $link = row_url($row, DO_CHECKS, 1, DO_RESULTS, 1);
            say multirow([$row->folder->name, $row->folder->title,
                          $row->user->name, $row->user->full_name,
                          ($row->date ?
                           ($row->date, href($link, "[check]")) :
                           ("(No uploads)", ""))], @file_rows);

            if ($do_checks and $row->date) {
                my @checkers = @{$row->folder->checkers};
                my $len = @checkers;
                my @indexes = (1..$len);
                my $passed = true {$_ == 0} pairwise
                { say indentrow(1,8,"Running @{[$b->[0]]} (check $a of $len)");
                  say start_indentrow(2, 8), $q->start_div();
                  system @{$b->[1]}, filename(
                      $row->folder->name, $row->user->name, $row->date);
                  die $! if $? == -1;
                  say $q->end_div(), end_indentrow();
                  say indentrow(2, 8, $? ? 'Failed' : 'Passed');
                  $?} @indexes, @checkers;
                say indentrow(1, 8, "Passed $passed of $len checks");
            }
            say $q->end_tbody();
        }
    }
    say $q->end_table();
}

sub folder_results {
    # Search
    my @folders = list_folders(@folders);

    # Print
    say $q->center(NO_RESULTS) unless @folders;
    foreach my $folder (@folders) {
        say $q->start_div({-class=>FOLDER});
        say $q->h3($folder->title,"(".$folder->name.") - due",$folder->due);
        say $q->div($folder->text);

        say $q->start_form(-method=>'POST', -enctype=>&CGI::MULTIPART,
                               -action=>$global_config->cgi_url);
        say $q->hidden(-name=>FOLDERS, -value=>$folder->name, -override=>1);
        say $q->hidden(-name=>DO_CHECKS, -value=>1, -override=>1);
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
    my ($row, @rest) = @_;
    form_url(FOLDERS, $row->folder->name, USERS, $row->user->name,
             START_DATE, $row->date, END_DATE, $row->date, @rest);
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

sub href { my ($href, @rest) = @_; $q->a({-href=>$href}, @rest); }
sub row { return $q->Tr($q->td([@_])); }
sub row_span { $q->Tr($q->td({-colspan=>$_[0]}, [@_[1..$#_]])); }
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

sub multirow {
    my ($prefix, @rows) = @_;
    return "<tr>" . $q->td({-rowspan=>scalar(@rows)}, $prefix) .
        join("</tr><tr>", (map { $q->td($_) } @rows)) . "</tr>";
}

sub error {
    print $q->header();
    say $q->start_html(-title=>$global_config->title . ": Error");
    say $q->h1($global_config->title . ": Error");
    my ($package, $filename, $line) = caller;
    say $q->p([@_, "(At line $line.)", "Go back and try again."]);
    exit 0;
}

################
# General Util
################

sub member {
    my ($value, $default, @list) = @_;
    return $default unless @list;
    return (grep { $_ eq $value } @list) ? 1 : 0;
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
