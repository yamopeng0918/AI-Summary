import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

const homepageSource = readFileSync(new URL('../pages/index.astro', import.meta.url), 'utf8');
const globalStyles = readFileSync(new URL('../styles/global.css', import.meta.url), 'utf8');

describe('summary card markup', () => {
  it('renders a linked, lazy-loaded OG image for each summary', () => {
    for (const markup of [
      "import { ogImagePath, summaryPath } from '../lib/paths';",
      'href={summaryPath(baseUrl, record.id)}',
      'src={ogImagePath(baseUrl, record.id)}',
      'alt={record.title}',
      'width="1200"',
      'height="630"',
      'loading="lazy"',
      'decoding="async"',
    ]) {
      expect(homepageSource).toContain(markup);
    }
  });

  it('sizes card images to their stable OG aspect ratio', () => {
    expect(globalStyles).toMatch(/\.summary-card-image\s*\{[^}]*aspect-ratio:\s*1200\s*\/\s*630[^}]*\}/);
    expect(globalStyles).toMatch(/\.summary-card-image\s*\{[^}]*object-fit:\s*cover[^}]*\}/);
    expect(globalStyles).toMatch(/\.summary-card-image\s*\{[^}]*width:\s*100%[^}]*\}/);
  });
});
