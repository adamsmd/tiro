#! /usr/bin/perl
use warnings; # Full warnings
use strict; # Strict error checking
$|++; # Unbuffer stdout
umask 0077; # Default to private files

use File::Slurp qw(slurp); # Perl 6 feature
sub say { print @_, "\n"; } # Emulate Perl 6 feature

my $gray = "style=\"background:rgb(95%,95%,95%);\"";

my $hash = parse_config($ENV{'TIRO_ASSIGNMENT'}, 'text', 'tests');
my @tests = @{$hash->{'tests'}};

my $len = @tests;
my $passed = 0;

say "<table style=\"width:100%\">";

for my $i (1..$len) {
  my ($name, $cmd) = $tests[$i-1] =~ /^\s*(.*?)\s*--\s*(.*?)\s*$/;
  say "<tr><td colspan=2 $gray>Running $name (test $i of $len)</td></tr>";
  say "<tr><td></td><td><div>";
  system $cmd;
  die $! if $? == -1;
  say "</div></td></tr>";
  say "<tr><td>&nbsp</td><td>", $? ? 'Failed' : 'Passed', "</td></tr>";
  $passed++ if $?;
}

say "<tr><td colspan=2 $gray>",
    $len ? "Passed $passed of $len tests" : "(No tests)", "</td></tr>";

say "</table>";

sub parse_config {
  my ($filename, $body_name, @lists) = @_;
  my ($lines, $body) = slurp($filename) =~ /^(.*?)(?:\n\s*\n(.*))?$/s;
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
  $hash{$body_name} =
    ($hash{$body_name} || "") . (($body || "") =~ /\S/ ? $body : "");
  return \%hash;
}
