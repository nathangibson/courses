#!/usr/bin/env ruby
# frozen_string_literal: true

# check_yaml_control_chars.rb
#
# Scans every YAML file under _data/ for raw control characters (C0 and C1)
# that Psych/libyaml rejects with a cryptic "control characters are not allowed
# at line 1 column 1" error, and fails the build with a clear message instead.
#
# Usage:  ruby scripts/check_yaml_control_chars.rb        (exit 1 on any hit)
#
# C0 controls (except tab/newline/CR) and all C1 controls (U+0080–U+009F,
# e.g. the Windows-1252 curly-quote bytes 0x91–0x97 and stray 0x92) are
# considered invalid in Jekyll `_data` YAML.  Better BibTeX's postscript
# sanitizer should strip them; this is a CI safety net.

require 'find'

BAD_C0 = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/

root = File.expand_path('_data', File.expand_path('..', __dir__))
failures = 0

unless Dir.exist?(root)
  warn "check_yaml_control_chars: #{root} not found; nothing to check."
  exit 0
end

Find.find(root) do |path|
  next unless path.end_with?('.yaml', '.yml')
  next if File.directory?(path)

  bytes = File.binread(path)
  utf8 = bytes.dup.force_encoding('UTF-8')

  # Real culprit that breaks Psych: a byte that is NOT valid UTF-8 on its own —
  # typically a lone C1 byte (Windows-1252 curly quote/dash, e.g. 0x92) that
  # appears in a valid-UTF-8 document. If the whole file decodes cleanly as
  # UTF-8, there are no lone C1 bytes (0x80-0x9F only appear as continuation
  # bytes of valid multibyte chars), so it's fine.
  unless utf8.valid_encoding?
    # Locate the first invalid byte sequence.
    bad_char = utf8.scrub('?').index('?')
    off = utf8[0...bad_char].bytesize rescue 0
    line = utf8[0...off].count("\n") + 1
    byte = bytes.getbyte(off) || 0
    failures += 1
    warn format('  invalid UTF-8 byte 0x%02X in %s (near line %d)', byte, path, line)
    next
  end

  # C0 controls (other than tab/newline/CR)
  if (m = BAD_C0.match(utf8))
    off = m.begin(0)
    line = utf8[0...off].count("\n") + 1
    failures += 1
    warn "  C0 control char U+#{m[0].ord.to_s(16).upcase} in #{path} (line #{line})"
  end
end

if failures.zero?
  puts 'check_yaml_control_chars: OK - no control characters in _data YAML.'
  exit 0
else
  warn "check_yaml_control_chars: #{failures} file(s) contain control characters."
  warn 'Fix the source in Zotero / Better BibTeX export (sanitizer strips these).'
  exit 1
end
