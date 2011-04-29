#! /usr/bin/perl -T
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout
umask 0077; # Default to private files
delete @ENV{qw(PATH IFS CDPATH ENV BASH_ENV)}; # Make %ENV safer

# Configuration
use constant CONFIG_FILE => 'system/config.cfg';
use lib 'system/lib';

# Modules from Core
use Carp qw(verbose);
use CGI qw(-private_tempfiles -nosticky);

# Modules not from Core
use Tiro;
use Date::Manip;
use File::Slurp qw/slurp/; # Perl 6 feature

################
## Bootstrap
my $tiro = Tiro->new(CONFIG_FILE);
my $q = CGI->new;
panic($q->cgi_error()) if $q->cgi_error();

my ($tainted_user) = $tiro->user_override || $q->remote_user() =~ /^(\w+)\@/;
my $login = my $real_login = $tiro->users()->{$tainted_user};
panic("No such user: $tainted_user.", "Missing HTTPS?") unless defined $login;
panic("User $tainted_user isn't an admin.") unless $login->is_admin;
panic("No log files defined.") unless $tiro->log_file ne "";

sub panic {
  print $q->header(-charset=>'utf8');
  say $q->start_html(-title=>"Error: " . $tiro->title, -encoding=>'utf8');
  say $q->h1("Error: " . $tiro->title);
  say $q->p([@_]);
  exit 0;
}

################
## Header
print $q->header(-charset=>'utf8');
print $q->start_html(-title=>'Logs for ' . $tiro->title, -encoding=>'utf8',
                     -style=>{-verbatim=><<'EOT'});
  td { vertical-align:top; text-align:left; border:solid 1px black; }
  select { vertical-align:top; }
EOT
print $q->h1("Logs for " . $tiro->title);

my @users = $q->param('users');
my @all_users = sort map {$_->id} values %{$tiro->users()};

print $q->start_form(-action=>'#');
print $q->p($q->strong('Select date: '),
            $q->textfield(-name=>'date', -value=>UnixDate('now')),
            $q->strong('Select users: '),
            $q->scrolling_list(-name=>'users', -multiple=>1, -size=>5,
                               -values=>[@all_users], -default=>[@all_users]));
print $q->p($q->submit(-value=>"Show Logs"));
print $q->end_form();

print $q->hr();

################
## Results
my %lines;
my $log_file = UnixDate($q->param('date'), $tiro->log_file);
if (not -f $log_file or not -r $log_file) {
  print $q->p("No such log file: $log_file");
} else {
  ## Find Results
  for (split("\n", slurp($log_file))) {
    my ($date, $prog, $pid, $user, $rest) =
      /^\[(.*?)\] (.*?) \(PID:(.*?) USER:(.*?)\): (.*)$/;
    if (defined $rest) {
      my $key = $user."\x00".$pid;
      $lines{$key} = [@{$lines{$key} || []}, [$date, $user, $pid, $rest]]
    }
  }

  ## Print Results
  print $q->h2('Results');
  print $q->start_table();
  for (sort {line_cmp($a) cmp line_cmp($b)} keys %lines) {
    my ($date, $user, $rest) = @{$lines{$_}->[0]};
    my ($id) = $user =~ /^(\w+)\@/;
    print $q->Tr($q->td([
                   "$date<br/>$user",
                   $q->pre(join("\n", map { $_->[3] } @{$lines{$_}}))]))
      if grep { $id eq $_ } @users;
  }
}
print $q->end_table();

print $q->end_html();

sub line_cmp {
  my ($date, $user, $pid, $rest) = @{$lines{$_[0]}->[0]};
  UnixDate($date, "%O")."\x00".$user."\x00".$pid;
}
