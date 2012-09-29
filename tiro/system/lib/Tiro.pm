package Tiro;

use warnings;
use strict;

# Modules from Core
use Carp;
use Class::Struct;
use Exporter qw(import);
use File::Spec::Functions;
use Text::ParseWords;

# Modules not from Core
use Date::Manip;
use File::Slurp qw/slurp/; # Perl 6 feature
use List::MoreUtils qw/:all/;

=head1 NAME

Tiro - The great new Tiro.pm!

=head1 VERSION

Version 0.02

=cut

our $VERSION = '0.02';

=head1 SYNOPSIS

This module contains access routines for accessing Tiro assignments and
submissions.

    use Tiro;

    my $tiro = Tiro->new('system/tiro.cfg');
    $tiro->title # string
    $tiro->admins # list of string of username
    $tiro->user_override # string of username
    $tiro->users # hash from username to Tiro::User
    $tiro->user_files # list of strings of header lines, id col, name col and filename words
    $tiro->path # string
    $tiro->max_post_size # number of bytes
    $tiro->date_format # string
    $tiro->log_file # string
    $tiro->assignments_dir # string of directory
    $tiro->assignments_regex # string of regex
    $tiro->submissions_dir # string
    $tiro->text # string of HTML
    $tiro->download_inline # regex on filename.  if matches, then downloads are inline

    $user->id # string of username
    $user->name # string of full name
    $user->is_admin # boolean

    $assignment->tiro # Tiro::Tiro
    $assignment->id # string
    $assignment->
    ...

    $submission

=head1 EXPORT

A list of functions that can be exported.  You can delete this section
if you don't export anything, such as for a purely object-oriented module.

=cut

our @EXPORT = qw(dir_list tiro_date same_group uniq_submissions cmp_alphanum);
our @EXPORT_OK = qw();

=head1 SUBROUTINES/METHODS

=head2 function1

=cut

sub dir_find {
  my ($pred, @dirs) = @_;

  my $dir;
  opendir(my $d, catdir(@dirs)) or return ();
  while (my $dir = readdir($d)) {
    next if $dir =~ m/^\./;
    (closedir $d and return $dir) if &$pred($dir);
  }

  closedir $d;
  return ();
}

sub dir_list {
  opendir(my $d, catdir(@_)) or return ();
  my @ds = readdir($d);
  closedir $d;
  return sort { cmp_alphanum($a, $b) } (grep {!/^\./} @ds); # skip dot files
}

# This should be equivalent to:
#   sub cmpx { # digits sort before non-digits
#     my ($x, $y) = @_;
#     ($x =~ /\d/ and $y =~ /\d/) ? $x <=> $y :
#     ($x =~ /\d/) ? -1 :
#     ($y =~ /\d/) ?  1 :
#     $x cmp $y;
#   }
#     
#   my @a = split /(\d+|\D)/, $_[0];
#   my @b = split /(\d+|\D)/, $_[1];
#   reduce { $a || $b } 0, (pairwise { cmpx(($a || ""), ($b || "")); } @a, @b);
# But the following algorithm doesn't have to search through the
# entire string if it finds a difference early.
sub cmp_alphanum {
  my @a = split /(\d+)/, $_[0];
  my @b = split /(\d+)/, $_[1];
  while (@a or @b) {
    #use bigint;
    my $res =
      (not @a and -1) ||
      (not @b and 1) ||
      ($a[0] =~ /\d/ and $b[0] =~ /\d/ and $a[0] <=> $b[0]) ||
      ($a[0] cmp $b[0]);
    return 0+$res if $res;
    shift @a;
    shift @b;
  }
  return 0;
}

sub tiro_date {
    my $r = qr[^(\d\d\d\d-\d\d-\d\dT\d\d:\d\d:\d\d)$];
    (UnixDate($_[0], "%O") or "") =~ m/$r/ unless $_[0] =~ m/$r/;
    return $1;
}

sub same_group {
  my ($assignment, $user1, $user2) = @_;
  (grep {$user2->id eq $_->id} @{$assignment->groups->{$user1->id}}) ? 1 : 0;
}

sub uniq_submissions {
  my %seen;
  grep { !$seen{$_->assignment->id."\x00".$_->user->id."\x00".$_->date}++} @_;
}

=head2 Tiro::Tiro

=cut

struct 'Tiro::Tiro'=>{
  title=>'$', admins=>'@', user_override=>'$', users=>'%', user_files=>'@', 
  path=>'$', max_post_size=>'$', date_format=>'$', log_file=>'$',
  assignments_dir=>'$', assignments_regex=>'$', submissions_dir=>'$', text=>'$',
  default_inline_regex=>'$', default_form_file=>'$', default_form_format=>'$',
  misc=>'%' };
struct 'Tiro::User'=>{id=>'$', name=>'$', is_admin=>'$'};
sub Tiro::new {
  my ($tiro_package, $file, @lists) = @_;

  my %config = (
    # General Configurations
    title => '',
    path => '/usr/local/bin:/usr/bin:/bin',
    max_post_size => 1000000,
    date_format => '%a, %b %d %Y, %r',
    log_file => 'system/log/log-%Y-%m-%d.txt',

    # Assignment Configurations
    assignments_dir => 'assignments',
    assignments_regex => qr[^(\w+)\.cfg$],
    submissions_dir => 'submissions',

    # User Configurations
    admins => [],
    user_override => '',
    users => {},
    user_files=>[],

    # Assignment Defaults
    default_inline_regex => '^(?!)$',
    default_form_file => 'form_responce.txt',
    default_form_format => '==+== [%k] %l%n%v%n%n'
    );

  if (defined $file) {
    my %c = parse_config_file(
      $file, 'text', 'admins', 'users', 'user_files', @lists);

    my @admins = (@{$config{'admins'} || []}, @{$c{'admins'}});
    my %users = (%{$config{'users'} || {}},
                 map { my ($id, $name) = quotewords(qr/\s+/, 0, $_);
                       ($id, { name => $name }) }
                 @{$c{'users'}});

    %config = (%config, %c, admins => \@admins, users => \%users);
  }

  my $tiro = Tiro::Tiro->new(%config, misc=>\%config);

  # Parse users
  my %users = %{$tiro->users};

  for my $file (@{$tiro->user_files}) {
    my ($header_lines, $id_col, $name_col, $file_name) =
      quotewords(qr/\s+/, 0, $file);

    my @lines = split("\n", slurp $file_name);
    for (@lines[$header_lines || 0..$#lines]) {
      if ((my @words = quotewords(",", 0, $_)) >= 2) {
        $words[$id_col] =~ s/(^\s*)|(\s*$)//g;
        $words[$name_col] =~ s/(^\s*)|(\s*$)//g;
        $users{$words[$id_col]} = { name => $words[$name_col] };
      }
    }
  }

  $users{$_}->{'is_admin'} = 1 for @{$tiro->admins};
  $users{$_}->{'is_admin'} ||= 0 for keys %users;

  $tiro->users({map { ($_, Tiro::User->new(id => $_, %{$users{$_}})) }
                (keys %users)});

  return $tiro;
}

sub Tiro::Tiro::query {
  my $tiro = shift;
  my %x = @_;
  %x = ('assignments' => [map { $tiro->assignment($_, @{$x{'users'}}) }
                          dir_list($tiro->assignments_dir)],
        'users' => [values %{$tiro->users}], 'login' => undef, 'groups' => 1,
        'start_date' => '', 'end_date' => '', 'failed' => 0,
        'only_latest' => 0, 'submissions_no' => 0, 'submissions_yes' => 1, %x);

  my @subs;
  for my $assignment (@{$x{'assignments'}}) {
    my @shown_users = (defined $x{'login'} and not $x{'login'}->is_admin) ?
      (grep {same_group($assignment, $x{'login'}, $_)} @{$x{'users'}}) :
      (@{$x{'users'}});
    for my $user (@shown_users) {
      my @dates = $assignment->submissions($user, $x{'groups'});
      @dates = grep {$x{'start_date'} le $_->date} @dates if $x{'start_date'};
      @dates = grep {$x{'end_date'} ge $_->date} @dates if $x{'end_date'};
      @dates = grep {not $_->failed} @dates if not $x{'failed'};
      @dates = ($dates[$#dates]) if $#dates != -1 and $x{'only_latest'};

      push @subs, $assignment->no_submissions($user)
        if $x{'submissions_no'} and not @dates;
      push @subs, @dates if $x{'submissions_yes'};
    }
  }
  return uniq_submissions(@subs);
}

=head2 Tiro::Assignment

=cut

struct 'Tiro::Assignment'=>{
  tiro=>'Tiro::Tiro',
  id=>'$', path=>'$', num_late=>'$', num_ontime=>'$', title=>'$',
  hidden_until=>'$', due=>'$', late_after=>'$', text=>'$', text_file=>'$', 
  file_count=>'$', inline_regex=>'$', reports=>'@', guards=>'@',
  groups=>'%', form_file=>'$', form_format=>'$', form_fields=>'@', 
  misc=>'%' };
sub Tiro::Tiro::assignment {
  my ($tiro, $path, @users) = @_;

  my ($id) = join('', $path =~ $tiro->assignments_regex);

  $id ne '' or return ();

  my @lists = ();
  my $file = catfile($tiro->assignments_dir, $path);

  my %file = parse_config_file(
    $file, 'text', 'reports', 'guards', 'groups', 'form_fields', @lists);

  $file{$_} = tiro_date($file{$_}) for ('due', 'late_after', 'hidden_until');
  defined $file{$_} or $file{$_} = "" for (
    'title', 'due', 'late_after', 'hidden_until',
    'text_file', 'text', 'file_count');
  exists $file{$_} or $file{$_} = $tiro->{"Tiro::Tiro::default_$_"}
      for ('inline_regex', 'form_file', 'form_format');

  my @groups = map {[quotewords(qr/\s+/, 0, $_)]} @{$file{'groups'}};
  $file{'groups'} = {};
  $file{'groups'}->{$_} = [$_] for (keys %{$tiro->users()});
  for my $group (@groups) {
    push @{$file{'groups'}->{$_}}, @$group for (@$group);
  }
  $file{'groups'}->{$_} = [
    map {$tiro->users()->{$_}} (sort (uniq(@{$file{'groups'}->{$_}})))]
    for (keys %{$tiro->users()});

  my $assignment = Tiro::Assignment->new(%file, tiro=>$tiro, misc=>\%file);
  $assignment->id($id);
  $assignment->path($path);
  $assignment->num_ontime('0');
  $assignment->num_late('0');
  for my $user (@users) {
    if (map { dir_find(sub { $_[0] !~ m[\.tmp$] and
                               not $assignment->late_if($_[0]) },
                       $tiro->submissions_dir,$assignment->id,$_->id)
        } @{$assignment->groups->{$user->id}}) {
      $assignment->num_ontime(1 + $assignment->num_ontime);
    } elsif (map { dir_find(sub { $_[0] !~ m[\.tmp$] },
                       $tiro->submissions_dir,$assignment->id,$_->id)
        } @{$assignment->groups->{$user->id}}) {
      $assignment->num_late(1 + $assignment->num_late);
    }
  }

  return $assignment;
}

sub Tiro::Assignment::no_submissions {
  my ($assignment, $user) = @_;
  my $group = $assignment->groups->{$user->id};
  Tiro::Submission->new(
    assignment=>$assignment, user=>$group->[0],
    date=>'', late=>0, group=>$group, files=>[],
    group_id=>join("\x00", map {$_->id} @$group),
    group_name=>join("\x00", map {$_->name} @$group));
}

=head2 Tiro::Submission

=cut

struct 'Tiro::Submission'=>{
  assignment=>'Tiro::Assignment', user=>'Tiro::User',
  group=>'@', group_id=>'$', group_name=>'$',
  date=>'$', files=>'@', failed=>'$', late=>'$'};
struct 'Tiro::File'=>{name=>'$', size=>'$'};
sub Tiro::Assignment::submissions {
  my ($assignment, $user, $group) = @_;
  my @users = $group ? @{$assignment->groups->{$user->id}} : ($user);
  my $tiro = $assignment->tiro();

  sort {$a->date cmp $b->date or $a->user->id cmp $b->user->id}
  grep {-d catfile($tiro->submissions_dir, $_->assignment->id, $_->user->id,
                   $_->date.$_->failed)}
  map { my $user = $_;
        map { $_ =~ /^(.*?)((\.tmp)?)$/;
              my $group = $assignment->groups->{$user->id};
              Tiro::Submission->new(
                assignment=>$assignment, user=>$user,
                date=>tiro_date($1),
                group=>$group,
                group_id=>join("\x00", map {$_->id} @$group),
                group_name=>join("\x00", map {$_->name} @$group),
                failed=>$2, late=>($1 gt late_after($assignment)),
                files=>[list_files($tiro, $assignment, $user, $1.$2)]);
        } dir_list($tiro->submissions_dir,$assignment->id,$user->id)
  } @users;
}

sub list_files {
  my ($tiro, $assignment, $user, $date) = @_;
  my @names = dir_list($tiro->submissions_dir,
                       $assignment->id, $user->id, $date);
  map { Tiro::File->new(name=>$_, size=>-s catfile(
                          $tiro->submissions_dir,
                          $assignment->id, $user->id, $date, $_)) } @names;
}

sub Tiro::Assignment::late_if {
  my ($assignment, $date) = @_;
  my $x = $assignment->late_after ne "" ? $assignment->late_after : $assignment->due;
  return $x ne "" && $date ge $x;
}

sub late_after { $_[0]->late_after ne "" ? $_[0]->late_after : $_[0]->due; }

=head2 parse_config_file

    my %config = parse_config_file($filename, $body_field_name,
      list_field_name1, list_field_name2, ...);

=cut

sub parse_config_file {
  my ($filename, $body_name, @lists) = @_;
  my ($lines, $body) = split(/^\n/m, slurp($filename), 2);
  my %hash = map { ($_, []) } @lists;
  for (split "\n", $lines) {
    my ($key, $value) = /^\s*([^:]*?)\s*:\s*(.*?)\s*$/;
    if (defined $key and defined $value) {
      if (grep { $_ eq $key } @lists) {
        push @{$hash{$key}}, $value;
      } else {
        $hash{$key} = $value;
      }
    }
  }
  $hash{$body_name} = ($hash{$body_name} || "") . ($body || "");
  return %hash;
}

=head1 AUTHOR

Michael D. Adams, C<< <www.cs.indiana.edu/~adamsmd/> >>

=head1 BUGS

Please report any bugs or feature requests to
C<http://www.cs.indiana.edu/~adamsmd/>.


=head1 SUPPORT

You can find documentation for this module with the perldoc command.

    perldoc Tiro::Config

You can also look for information at: TODO


=head1 ACKNOWLEDGEMENTS


=head1 LICENSE AND COPYRIGHT

Copyright 2011 Michael D. Adams.

This program is free software; you can redistribute it and/or modify it
under the terms of either: the GNU General Public License as published
by the Free Software Foundation; or the Artistic License.

See http://dev.perl.org/licenses/ for more information.


=cut

1; # End of Tiro::Config
