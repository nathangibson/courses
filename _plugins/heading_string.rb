# frozen_string_literal: true

# _plugins/heading_string.rb
#
# Liquid filter: heading_string(headings, key, lang, type, default_type, fallback)
#
# Resolve a session-detail heading's display string from the global headings
# config (site.data.headings), nested heading -> language -> type:
#
#     readings:
#       de:
#         lecture: "Empfohlene Literatur"
#         seminar: "Pflichtlektüre"
#       en:
#         lecture: "Suggested readings"
#         seminar: "Required readings"
#
# A heading may also be written type-independently as a plain string per
# language:
#
#     learning_objective:
#       de: "Lernziel"
#       en: "Learning objective"
#
# Fallback chain for a course with (language, type):
#   1. headings[key][lang][type]
#   2. headings[key][lang][default_type]   (default type, e.g. "seminar")
#   3. headings[key][lang]                 (plain string -- type-independent)
#   4. English: repeat steps 1-3 with lang = "en"
#   5. fallback                            (the hardcoded English default)
#
# Used via the heading.html include; the raw filter is also callable directly.

module Jekyll
  module HeadingStringFilter
    def heading_string(headings, key, lang, type, default_type, fallback)
      return fallback if headings.nil? || key.nil?

      node = headings[key]
      return fallback if node.nil? || node.is_a?(Array) && node.empty?

      # Plain string at the top level (no language split): use it wholesale.
      if node.is_a?(String)
        return node unless node.empty?
        return fallback
      end

      # Resolve within one language node: it is either a plain string
      # (type-independent) or a { type => string } map.
      resolve_lang = lambda do |lang_node|
        next nil if lang_node.nil?
        if lang_node.is_a?(String)
          next (lang_node.empty? ? nil : lang_node)
        end
        if lang_node.is_a?(Hash)
          t = lang_node[type]
          return t unless t.nil? || t.to_s.empty?
          d = lang_node[default_type]
          return d unless d.nil? || d.to_s.empty?
        end
        nil
      end

      lang = lang.to_s

      # Course-language resolution.
      r = resolve_lang.call(node[lang])
      return r unless r.nil?

      # English resolution (steps repeat with lang = "en").
      r = resolve_lang.call(node["en"])
      return r unless r.nil?

      fallback
    end
  end
end

Liquid::Template.register_filter(Jekyll::HeadingStringFilter)
