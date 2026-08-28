import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

const layoutSource = readFileSync(new URL('../layouts/BaseLayout.astro', import.meta.url), 'utf8');
const detailPageSource = readFileSync(new URL('../pages/summaries/[id].astro', import.meta.url), 'utf8');

describe('summary social metadata', () => {
  it('declares optional metadata props and emits canonical, Open Graph, and Twitter metadata', () => {
    for (const prop of [
      'description?: string',
      'canonicalUrl?: string',
      'ogImageUrl?: string',
      'ogImageAlt?: string',
      "pageType?: 'website' | 'article'",
    ]) {
      expect(layoutSource).toContain(prop);
    }

    for (const metadata of [
      '<link rel="canonical" href={canonicalUrl} />',
      '<meta property="og:title" content={title} />',
      '<meta property="og:description" content={description} />',
      '<meta property="og:type" content={pageType} />',
      '<meta property="og:url" content={canonicalUrl} />',
      '<meta property="og:image" content={ogImageUrl} />',
      '<meta property="og:image:width" content="1200" />',
      '<meta property="og:image:height" content="630" />',
      '<meta property="og:image:alt" content={ogImageAlt} />',
      '<meta name="twitter:card" content="summary_large_image" />',
      '<meta name="twitter:title" content={title} />',
      '<meta name="twitter:description" content={description} />',
      '<meta name="twitter:image" content={ogImageUrl} />',
    ]) {
      expect(layoutSource).toContain(metadata);
    }
  });

  it('creates base-aware absolute summary and image URLs for detail metadata', () => {
    expect(detailPageSource).toContain("import { homePath, ogImagePath, summaryPath } from '../../lib/paths';");
    expect(detailPageSource).toContain('if (!Astro.site)');
    expect(detailPageSource).toContain('new URL(summaryPath(baseUrl, record.id), Astro.site)');
    expect(detailPageSource).toContain('new URL(ogImagePath(baseUrl, record.id), Astro.site)');
    expect(detailPageSource).toContain('description={record.summary}');
    expect(detailPageSource).toContain('canonicalUrl={canonicalUrl.href}');
    expect(detailPageSource).toContain('ogImageUrl={ogImageUrl.href}');
    expect(detailPageSource).toContain('ogImageAlt={record.title}');
    expect(detailPageSource).toContain('pageType="article"');
  });
});
