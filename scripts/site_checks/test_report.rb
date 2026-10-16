# frozen_string_literal: true

# scripts/site_checks/test_report.rb
#
# Shared result model for the site test suite. Every check yields findings
# (hashes) through a Reporter, which applies waivers and prints both the
# human-readable console output and the machine-readable test-results.json.
#
# Severity model (the "override" requirement):
#   ERROR  — blocks the build (rake lint/ci exit 1)
#   WARN   — printed with fix guidance, never blocks
#   WAIVED — an ERROR/WARN explicitly suppressed in config/test_waivers.yml;
#            still shown, never blocking
#
# Console contract (the file/line requirement):
#   ERROR [check-id] <file>:<line> — <problem> | fix: <one-liner> | sanitizer: <what a tool could do>
#   WARN  [check-id] <file> — <problem> | fix: <one-liner>
#   OK    [check-id] <summary>
#
# test-results.json: {run: {...}, findings: [{severity, check_id, file, line,
# message, fix, sanitizer, waived}]} so automated sanitizers can consume it.

require 'json'
require 'time'

module SiteChecks
  class Reporter
    attr_reader :findings, :oks

    def initialize(waivers_path: nil, io: $stdout)
      @io = io
      @findings = []
      @oks = []
      @waivers = load_waivers(waivers_path)
      @started = Time.now
    end

    # Accepts a finding hash; applies waivers; prints immediately.
    def emit(finding)
      f = normalize(finding)
      waiver_reason = waived?(f)
      if waiver_reason
        f[:waived] = true
        f[:waiver_reason] = waiver_reason
        severity = 'WAIVED'
      else
        severity = f[:severity]
      end
      print_finding(severity, f)
      @findings << f
      f
    end

    def ok(check_id, summary)
      @oks << { check_id: check_id, summary: summary }
      @io.puts format('OK    [%s] %s', check_id, summary)
    end

    def errors
      @findings.reject { |f| f[:waived] || f[:severity] == 'WARN' }
    end

    def warnings
      @findings.select { |f| !f[:waived] && f[:severity] == 'WARN' }
    end

    def waived
      @findings.select { |f| f[:waived] }
    end

    # Exit code: 0 = pass (errors may exist only as WAIVED), 1 = blocked.
    def exit_code
      errors.empty? ? 0 : 1
    end

    def write_json(path)
      doc = {
        'run' => {
          'started_at' => @started.utc.iso8601,
          'finished_at' => Time.now.utc.iso8601,
          'exit_code' => exit_code,
          'counts' => {
            'errors' => errors.size,
            'warnings' => warnings.size,
            'waived' => waived.size,
            'ok_checks' => @oks.size
          }
        },
        'findings' => @findings.map { |f| stringify_keys(f) },
        'ok_checks' => @oks.map { |o| stringify_keys(o) }
      }
      File.write(path, JSON.pretty_generate(doc) + "\n")
      path
    end

    def summary_line
      counts = []
      counts << "#{errors.size} error(s)" unless errors.empty?
      counts << "#{warnings.size} warning(s)" unless warnings.empty?
      counts << "#{waived.size} waived" unless waived.empty?
      counts << 'all checks passed' if counts.empty?
      counts.join(', ')
    end

    private

    def normalize(f)
      {
        severity: f[:severity] || 'ERROR',
        check_id: f[:check_id] || 'unknown',
        file: f[:file],
        line: f[:line],
        message: f[:message] || '',
        fix: f[:fix],
        sanitizer: f[:sanitizer]
      }
    end

    def print_finding(severity, f)
      loc = f[:file] ? (f[:line] ? "#{f[:file]}:#{f[:line]}" : f[:file].to_s) : '(no file)'
      line = format('%-6s [%s] %s — %s', severity, f[:check_id], loc, f[:message])
      line += " | fix: #{f[:fix]}" if f[:fix]
      line += " | sanitizer: #{f[:sanitizer]}" if f[:sanitizer]
      line += " | waived: #{f[:waiver_reason]}" if f[:waived]
      (@io.puts line)
    end

    # Waivers: config/test_waivers.yml
    #   <check-id>:
    #     - path: "regex or glob on source file path"
    #       line: 42          (optional)
    #       reason: "why acceptable"
    def load_waivers(path)
      return {} unless path && File.file?(path)
      require 'yaml'
      YAML.safe_load(File.read(path)) || {}
    rescue StandardError => e
      @io.puts "WARN  [waivers] could not load #{path}: #{e.message} — running without waivers"
      {}
    end

    def waived?(f)
      rules = @waivers[f[:check_id]]
      return nil unless rules.is_a?(Array)
      rules.each do |rule|
        next unless rule.is_a?(Hash)
        next unless rule['path']
        pattern = Regexp.new(rule['path'])
        next unless f[:file] && pattern.match?(f[:file])
        if rule['line']
          next unless f[:line].to_i == rule['line'].to_i
        end
        return rule['reason'] || 'waived in config/test_waivers.yml'
      end
      nil
    end

    def stringify_keys(h)
      h.each_with_object({}) { |(k, v), o| o[k.to_s] = v }
    end
  end
end
