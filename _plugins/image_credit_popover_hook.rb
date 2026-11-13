# frozen_string_literal: true

# _plugins/image_credit_popover_hook.rb
#
# Jekyll :post_render hook — automatically add image-credit popover buttons to
# every <img> whose image has usable credit data in _data/image_credits.yaml.
#
# Works for markdown images (![alt](...)), img-row.html images, and any other
# <img> referencing an internal assets/img/... path — no per-image include
# needed. The button uses the same data-toggle="popover" / data-content
# attributes as image-caption.html, so the site's popover initialization
# (Bootstrap on the main site, native on the courses site) drives it.

module Jekyll
  Jekyll::Hooks.register :documents, :post_render do |doc|
    next unless doc.output =~ %r{<img[^>]*src="[^"]*assets/img/}

    site = doc.site
    credits = site.data['image_credits'] || {}
    next if credits.empty?

    doc.output = doc.output.gsub(%r{<img([^>]*)src="([^"]*assets/img/[^"]+)"([^>]*)/?>}) do
      full = Regexp.last_match(0)
      pre = Regexp.last_match(1)
      src = Regexp.last_match(2)
      post = Regexp.last_match(3)

      key = File.basename(src, '.*')
      credit = credits[key]
      next full if credit.nil? || credit.empty?
      # Skip images that already have a credit button (e.g. featured images
      # rendered by featured-image.html emit data-image-credit-src="<src>").
      next full if doc.output.include?("data-image-credit-src=\"#{src}\"")
      # Skip if this img tag itself is already a popover trigger.
      next full if full =~ /data-toggle="popover"/ || pre =~ /data-toggle="popover"/

      sentence = build_sentence(credit)
      next full if sentence.nil? || sentence.empty?

      btn = %(<button class="btn credit-popover-btn" data-toggle="popover") +
            %( data-trigger="click" data-placement="bottom" data-html="true") +
            %( data-content="#{sentence.gsub('"', '&quot;')}" ) +
            %( data-image-credit-src="#{src}" title="Image Credit">) +
            %(<i class="fa-regular fa-image" aria-hidden="true"></i></button>)

      # Wrap img + button in a relative container so the button overlays the
      # image's bottom-right corner.
      %(<span class="img-credit-wrap">#{full}#{btn}</span>)
    end
  end

  # Build the credit sentence from the image_credits.yaml entry, mirroring
  # image-caption.html's format.
  def self.build_sentence(credit)
    parts = []
    parts << "Image: #{credit['description']}." if credit['description'].to_s != ''
    parts << "By #{credit['creator']}." if credit['creator'].to_s != ''
    parts << "#{credit['identifier']}." if credit['identifier'].to_s != ''
    if credit['publisher'].to_s != '' || credit['source_url'].to_s != ''
      src = ' Source:'
      src += " #{credit['publisher']}" if credit['publisher'].to_s != ''
      src += ',' if credit['publisher'].to_s != '' && credit['source_url'].to_s != ''
      if credit['source_url'].to_s != ''
        domain = credit['source_url'].to_s
                   .sub(%r{https?://}, '').split('/').first
        src += %( <a href="#{credit['source_url']}" target="_blank" rel="noopener">#{domain}</a>)
      end
      src += '.'
      parts << src
    end
    parts << "#{credit['rights']}." if credit['rights'].to_s != ''
    parts.join(' ').gsub(/\s+/, ' ').strip
  end
end
