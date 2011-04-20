package Tiro::Config;

use warnings;
use strict;

# Modules from Core
use Carp;
use Class::Struct;
use Exporter qw(import);
use Text::ParseWords;

# Modules not from Core
use Date::Manip;
use File::Slurp qw/slurp/; # Perl 6 feature
use List::MoreUtils qw/:all/;

=head1 NAME

Tiro::Config - The great new Tiro::Config!

=head1 VERSION

Version 0.01

=cut

our $VERSION = '0.01';


=head1 SYNOPSIS

Quick summary of what the module does.

Perhaps a little code snippet.

    use Tiro::Config;

    my $foo = Tiro::Config->new();
    ...

=head1 EXPORT

A list of functions that can be exported.  You can delete this section
if you don't export anything, such as for a purely object-oriented module.

=cut

our @EXPORT = qw(
  parse_global_config_file parse_assignment_file parse_user_configs
  GlobalConfig UserConfig AssignmentConfig empty_user);
our @EXPORT_OK = qw();

=head1 SUBROUTINES/METHODS

=head2 function1

=cut

sub date { ((UnixDate($_[0], "%O") or "") =~ m[^([A-Za-z0-9:-]+)$])[0]; }

# Configuration
my %global_config_default = (
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
  users_file=>'',
  );

defined $global_config_default{$_} or $global_config_default{$_} = ""
  for ('config_file', 'log_file', 'users_file');

struct GlobalConfig=>{
  title=>'$', admins=>'*@', user_override=>'$', users=>'*%', user_files=>'@', 
  path=>'$', max_post_size=>'$', date_format=>'$', log_file=>'$',
  assignments_dir=>'$', assignments_regex=>'$', submissions_dir=>'$',
  text=>'$', misc=>'%' };
struct UserConfig=>{id=>'$', full_name=>'$', is_admin=>'$'};
struct AssignmentConfig=>{
  id=>'$', path=>'$', dates=>'@', title=>'$', hidden_until=>'$',
  text_file=>'$', due=>'$', late_after=>'$', file_count=>'$', reports=>'@',
  guards=>'@', text=>'$', groups=>'%' , misc=>'%' };

=head2 parse_global_config_file

=cut

sub parse_global_config_file {
  my ($file, @lists) = @_;

  my %config = %global_config_default;

  if (defined $file) {
    my %c = parse_config_file(
      $file, 'text', 'admins', 'users', 'user_files', @lists);

    my @admins = (@{$config{'admins'} || []}, @{$c{'admins'}});
    my %users = (%{$config{'users'} || {}},
                 map { my ($id, $name) = quotewords(qr/\s+/, 0, $_);
                       ($id, { full_name => $name }) }
                 @{$c{'users'}});

    %config = (%config, %c, admins => \@admins, users => \%users);
  }

  return GlobalConfig->new(%config, misc=>\%config);
}

=head2 parse_assignment_file

=cut

sub parse_assignment_file {
  my ($users, $file, @lists) = @_;

  my %file = parse_config_file(
    $file, 'text', 'reports', 'guards', 'groups', @lists);

  $file{$_} = date($file{$_}) for ('due', 'late_after', 'hidden_until');
  defined $file{$_} or $file{$_} = "" for (
    'due', 'late_after', 'hidden_until', 'text_file', 'text', 'file_count');

  my @groups = map {[quotewords(qr/\s+/, 0, $_)]} @{$file{'groups'}};
  $file{'groups'} = {};
  $file{'groups'}->{$_} = [$_] for (keys %$users);
  for my $group (@groups) {
    push @{$file{'groups'}->{$_}}, @$group for (@$group);

  }
  $file{'groups'}->{$_} = [map {$users->{$_}} (sort (uniq(@{$file{'groups'}->{$_}})))]
    for (keys %$users);

  return AssignmentConfig->new(%file, misc=>\%file);
}

=head2 parse_user_configs

=cut

sub drop { @_[$_[0]+1..$#_] }

sub parse_user_configs {
  my ($global_config) = @_;

  my %users = %{$global_config->users};

  for my $file (@{$global_config->user_files}) {
    my ($header_lines, $id_col, $full_name_col, $file_name) =
      quotewords(qr/\s+/, 0, $file);

    for (drop($header_lines || 0, split("\n", slurp $file_name))) {
      my @words = quotewords(",", 0, $_);
      my $id = $words[$id_col];
      my $full_name = $words[$full_name_col];
      if (defined $id and defined $full_name) {
        $users{$id} = { full_name => $full_name };
      }
    }
  }

  $users{$_}->{'is_admin'} = 1 for @{$global_config->admins};
  $users{$_}->{'is_admin'} ||= 0 for keys %users;

  return map { ($_, UserConfig->new(id => $_, %{$users{$_}})) } (keys %users);
}

sub empty_user { UserConfig->new(id => '', full_name => '', is_admin => '') }

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

Please report any bugs or feature requests to C<bug-tiro-config at rt.cpan.org>, or through
the web interface at L<http://rt.cpan.org/NoAuth/ReportBug.html?Queue=Tiro-Config>.  I will be notified, and then you'll
automatically be notified of progress on your bug as I make changes.




=head1 SUPPORT

You can find documentation for this module with the perldoc command.

    perldoc Tiro::Config


You can also look for information at:

=over 4

=item * RT: CPAN's request tracker

L<http://rt.cpan.org/NoAuth/Bugs.html?Dist=Tiro-Config>

=item * AnnoCPAN: Annotated CPAN documentation

L<http://annocpan.org/dist/Tiro-Config>

=item * CPAN Ratings

L<http://cpanratings.perl.org/d/Tiro-Config>

=item * Search CPAN

L<http://search.cpan.org/dist/Tiro-Config/>

=back


=head1 ACKNOWLEDGEMENTS


=head1 LICENSE AND COPYRIGHT

Copyright 2011 Michael D. Adams.

This program is free software; you can redistribute it and/or modify it
under the terms of either: the GNU General Public License as published
by the Free Software Foundation; or the Artistic License.

See http://dev.perl.org/licenses/ for more information.


=cut

1; # End of Tiro::Config
