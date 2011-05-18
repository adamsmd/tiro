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

our @EXPORT = qw(dir_list tiro_date same_group uniq_submissions);
our @EXPORT_OK = qw();

=head1 SUBROUTINES/METHODS

=head2 function1

=cut

sub dir_list {
  opendir(my $d, catdir(@_)) or return ();
  my @ds = readdir($d);
  closedir $d;
  return sort grep {!/^\./} @ds; # skip dot files
}

sub tiro_date { ((UnixDate($_[0], "%O") or "") =~ m[^([A-Za-z0-9:-]+)$])[0]; }

sub same_group {
  my ($assignment, $user1, $user2) = @_;
  warn "user1:", $user1->id;
  warn "user2:", $user2->id;
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
  assignments_dir=>'$', assignments_regex=>'$', submissions_dir=>'$',
  text=>'$', misc=>'%' };
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
      my @words = quotewords(",", 0, $_);
      my $id = $words[$id_col];
      my $name = $words[$name_col];
      $users{$id} = { name => $name } if defined $id and defined $name;
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
  id=>'$', path=>'$', dates=>'@', title=>'$', hidden_until=>'$',
  text_file=>'$', due=>'$', late_after=>'$', file_count=>'$', reports=>'@',
  guards=>'@', text=>'$', groups=>'%' , misc=>'%' };
sub Tiro::Tiro::assignment {
  my ($tiro, $path, @users) = @_;

  my ($id) = join('', $path =~ $tiro->assignments_regex);

  $id ne '' or return ();

  my @lists = ();
  my $file = catfile($tiro->assignments_dir, $path);

  my %file = parse_config_file(
    $file, 'text', 'reports', 'guards', 'groups', @lists);

  $file{$_} = tiro_date($file{$_}) for ('due', 'late_after', 'hidden_until');
  defined $file{$_} or $file{$_} = "" for (
    'title', 'due', 'late_after', 'hidden_until', 'text_file', 'text', 'file_count');

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
  $assignment->dates([
    map { $_ ? $_ : () }
    map {
      firstval {not $_->failed}
      sort {$a->date cmp $b->date}
      $assignment->submissions(@{$assignment->groups->{$_->id}})
    } @users]);
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
                assignment=>$assignment, user=>$user, date=>tiro_date($1),
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
  return $x ne "" and $date ge $x;
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
