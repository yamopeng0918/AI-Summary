import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

const homepageSource = readFileSync(new URL('../pages/index.astro', import.meta.url), 'utf8');
const globalStyles = readFileSync(new URL('../styles/global.css', import.meta.url), 'utf8');

describe('editorial homepage cards', () => {
  it('marks only the newest published record as the featured card', () => {
    expect(homepageSource).toContain('summaries.map((record, index) =>');
    expect(homepageSource).toContain("index === 0 && 'summary-card--featured'");
    expect(homepageSource).toContain('data-summary-card={record.id}');
  });

  it('renders one keyboard-focusable card link with a labelled OG image', () => {
    for (const markup of [
      "import { ogImagePath, summaryPath } from '../lib/paths';",
      'class="summary-card-link"',
      'href={summaryPath(baseUrl, record.id)}',
      'src={ogImagePath(baseUrl, record.id)}',
      'alt={record.title}',
      'width="1200"',
      'height="630"',
      'loading="lazy"',
      'decoding="async"',
      'class="summary-card-image-fallback"',
    ]) {
      expect(homepageSource).toContain(markup);
    }
    expect(homepageSource).not.toContain("loading={index === 0 ? 'eager' : 'lazy'}");
  });

  it('uses one source label for each card metadata row and image fallback', () => {
    expect(homepageSource).toContain("import { serializeSummaryRecords, sourceLabel } from '../lib/summaries';");
    expect(homepageSource).toContain('const source = sourceLabel(record);');
    expect(homepageSource).toMatch(/class="summary-card-image-fallback"[^>]*>\s*\{source\}/);
    expect(homepageSource).toMatch(/class="card-meta"[\s\S]*?<span>\{source\}<\/span>/);
  });

  it('reveals the source fallback while an OG image is unavailable', () => {
    expect(homepageSource).toContain("import { initializeSummaryImage } from '../lib/summary-image-state';");
    expect(homepageSource).toContain("querySelectorAll<HTMLImageElement>('.summary-card-image')");
    expect(homepageSource).toContain('initializeSummaryImage(image)');
    expect(globalStyles).toContain('.summary-card-image[data-image-state]:not([data-image-state="loaded"]) { opacity: 0; }');
    expect(globalStyles).toMatch(/\.summary-card-image\s*\{[^}]*display:\s*block[^}]*opacity:\s*1[^}]*\}/);
    expect(globalStyles).not.toContain('.summary-card-image[data-image-state]:not([data-image-state="loaded"]) { display: none; }');
  });

  it('contains OG images without cropping or distortion', () => {
    expect(globalStyles).toMatch(/\.summary-card-image-frame\s*\{[^}]*aspect-ratio:\s*1200\s*\/\s*630[^}]*\}/);
    expect(globalStyles).toMatch(/\.summary-card-image\s*\{[^}]*height:\s*100%[^}]*object-fit:\s*contain[^}]*width:\s*100%[^}]*\}/);
    expect(globalStyles).not.toMatch(/\.summary-card-image\s*\{[^}]*object-fit:\s*cover[^}]*\}/);
  });

  it('defines featured, three-column, tablet, and mobile layouts', () => {
    expect(globalStyles).toMatch(/\.summary-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)[^}]*\}/);
    expect(globalStyles).toMatch(/\.summary-card--featured\s*\{[^}]*grid-column:\s*1\s*\/\s*-1[^}]*\}/);
    expect(globalStyles).toMatch(/@media\s*\(max-width:\s*56rem\)[\s\S]*?\.summary-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
    expect(globalStyles).toMatch(/@media\s*\(max-width:\s*42rem\)[\s\S]*?\.summary-grid\s*\{[^}]*grid-template-columns:\s*1fr/);
  });

  it('stacks featured content before its image on tablet and mobile', () => {
    const tabletStyles = globalStyles.match(/@media\s*\(max-width:\s*56rem\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? '';

    expect(tabletStyles).toMatch(/\.summary-card--featured \.summary-card-image-frame[^}]*grid-row:\s*2/);
    expect(tabletStyles).toMatch(/\.summary-card--featured \.summary-card-content[^}]*grid-row:\s*1/);
  });
});
