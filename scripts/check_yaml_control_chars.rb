#!/usr/bin/env ruby
# frozen_string_literal: true

# check_yaml_control_chars.rb
#
# Scans every YAML file under _data/ (plus _config.yml) for characters that
# Psych/libyaml rejects with a cryptic "control characters are not allowed"
# error, and fails with a clear message naming the exact file and line.
#
# This is the CI SAFETY NET. The PRIMARY control-characters filter is the
# Zotero Better BibTeX postscript sanitizer (sanitizeAll/sanitizeString),
# which strips C0/C1 at export time (session 20261008_073304_a07e27).
# If this check fires, a control char slipped past the postscript.
#
# What counts as bad (YAML 1.1 printable set):
#   - stray Windows-1252 bytes: file is INVALID UTF-8 (e.g. a lone 0x92
#     right-single-quote from Zotero). Multi-byte UTF-8 continuation bytes
#     of legitimate characters (em-dash E2 80 94, umlaut C3 BC) are fine —
#     only bytes that break UTF-8 validity are flagged, with their
#     probable Windows-1252 interpretation shown.
#   - C0 controls except tab/newline/CR, plus DEL (U+007F)
#   - C1 controls (U+0080-U+009F except NEL U+0085) as actual codepoints
#     in otherwise-valid UTF-8
#
# Usage:  ruby scripts/check_yaml_control_chars.rb        (exit 1 on any hit)
#         require_relative 'check_yaml_control_chars'     (module use: run(reporter))

require 'find'

module SiteChecks
  module YamlControlChars
    # C0 except tab(09)/LF(0A)/CR(0D), plus DEL(7F); C1 except NEL(85)
    BAD_CODEPOINTS = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F\u0080-\u0084\u0086-\u009F]/

    module_function

    # Yields findings: {severity:, check_id:, file:, line:, message:, fix:, sanitizer:}
    def each_finding(repo_root)
      targets(repo_root).each do |path|
        bytes = File.binread(path)
        utf8 = bytes.dup.force_encoding('UTF-8')

        if utf8.valid_encoding?
          scan_codepoints(path, utf8) { |f| yield f }
        else
          scan_stray_bytes(path, bytes) { |f| yield f }
        end
      end
    end

    def run(reporter, repo_root)
      found = 0
      each_finding(repo_root) { |f| reporter.emit(f); found += 1 }
      reporter.ok('yaml-control-chars', ok_summary(repo_root)) if found.zero?
      found.zero?
    end

    def targets(repo_root)
      list = []
      config = File.join(repo_root, '_config.yml')
      list << config if File.file?(config)
      data_dir = File.join(repo_root, '_data')
      if Dir.exist?(data_dir)
        Find.find(data_dir) do |path|
          next unless path.end_with?('.yaml', '.yml')
          next if File.directory?(path)
          list << path
        end
      end
      list
    end

    # Valid UTF-8: scan decoded string for bad control codepoints.
    def scan_codepoints(path, utf8)
      return unless (m = BAD_CODEPOINTS.match(utf8))
      line = utf8[0...m.begin(0)].count("\n") + 1
      yield finding(path, line,
                    "control char U+#{m[0].ord.to_s(16).upcase.rjust(4, '0')} (valid UTF-8 file)",
                    'delete the control character or replace it with a space')
    end

    # Invalid UTF-8: locate the exact stray bytes (e.g. lone Windows-1252 0x92).
    def scan_stray_bytes(path, bytes)
      b = bytes.unpack('C*')
      i = 0
      reported = []
      while i < b.length
        lead = b[i]
        len = seq_len(lead)
        seq = b[i, len]
        if len == 1 && lead >= 0x80 || seq.nil? || seq.length < len || (len > 1 && seq[1..].any? { |c| (c & 0xC0) != 0x80 })
          unless reported.include?(lead)
            line = line_of_byte_offset(bytes, i)
            hint = begin
              lead.chr(Encoding::Windows_1252).encode(Encoding::UTF_8)
            rescue StandardError
              '?'
            end
            yield finding(path, line,
                          "stray byte 0x#{lead.to_s(16).upcase} (invalid UTF-8; likely Windows-1252 '#{hint}')",
                          'replace with the intended character (curly quote → ’, dash → –/—) or re-export from Zotero')
            reported << lead
          end
          i += 1
        else
          i += len
        end
      end
    end

    def seq_len(lead)
      return 1 if lead < 0x80
      return 2 if lead < 0xE0
      return 3 if lead < 0xF0
      4
    end

    def finding(path, line, what, fix)
      { severity: 'ERROR', check_id: 'yaml-control-chars',
        file: path, line: line,
        message: "#{what} - Psych would reject this YAML with a cryptic error",
        fix: fix,
        sanitizer: 'strip/replace control bytes (postscript sanitizer, cp1252→UTF-8 transcode)' }
    end

    def line_of_byte_offset(bytes, off)
      utf8 = bytes[0...off].dup.force_encoding('UTF-8')
      utf8.scrub.count("\n") + 1
    rescue StandardError
      1
    end

    def count_yaml(repo_root)
      targets(repo_root).size
    end

    def ok_summary(repo_root)
      "no control characters in _data YAML + _config.yml (#{count_yaml(repo_root)} files scanned)"
    end
  end
end

# Standalone CLI (also the CI entry point)
if __FILE__ == $PROGRAM_NAME
  repo_root = File.expand_path('..', __dir__)
  hits = []
  SiteChecks::YamlControlChars.each_finding(repo_root) { |f| hits << f }
  hits.each do |f|
    warn format('ERROR [%s] %s:%s — %s | fix: %s | sanitizer: %s',
                f[:check_id], f[:file], f[:line], f[:message], f[:fix], f[:sanitizer])
  end
  if hits.empty?
    puts "check_yaml_control_chars: OK - #{SiteChecks::YamlControlChars.ok_summary(repo_root)}."
    exit 0
  else
    warn "check_yaml_control_chars: #{hits.size} finding(s). Primary filter: Zotero Better BibTeX postscript sanitizer - re-export with it, or fix manually."
    exit 1
  end
end
