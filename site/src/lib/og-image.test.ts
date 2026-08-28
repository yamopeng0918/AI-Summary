import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it, vi } from 'vitest';
import sharp from 'sharp';
import type { SummaryRecord } from './summaries';
import {
  assertFontCoversStrings,
  createOgImageContent,
  createOgImageLayout,
  fitOgText,
  renderOgImage,
} from './og-image';

const record: SummaryRecord = {
  schemaVersion: 1,
  id: 'demo',
  canonicalUrl: 'https://news.example.com/articles/demo',
  sourceType: 'web',
  title: '這是一篇需要自動換行的繁體中文長標題',
  author: '王小明',
  sourcePublishedAt: null,
  createdAt: '2026-08-26T17:00:00+08:00',
  updatedAt: '2026-08-26T17:00:00+08:00',
  summary: '第一句摘要說明文章內容。第二句補充關鍵背景。第三句不應完整顯示。',
  keyPoints: ['重點一', '重點二', '重點三'],
  category: '人工智慧',
  tags: ['AI'],
  editorial: '編輯觀點',
  status: 'published',
};

interface PixelRegion {
  left: number;
  top: number;
  width: number;
  height: number;
}

async function countDarkGreenPixels(png: Buffer, region: PixelRegion): Promise<number> {
  const { data, info } = await sharp(png).raw().toBuffer({ resolveWithObject: true });
  let count = 0;
  for (let y = region.top; y < region.top + region.height; y += 1) {
    for (let x = region.left; x < region.left + region.width; x += 1) {
      const offset = (y * info.width + x) * info.channels;
      if (data[offset] < 90 && data[offset + 1] < 110 && data[offset + 2] < 110) {
        count += 1;
      }
    }
  }
  return count;
}

describe('OG image content', () => {
  it('renders a non-empty 1200 by 630 PNG with Chinese content', async () => {
    const png = await renderOgImage(record);
    const metadata = await sharp(png).metadata();

    expect(png.byteLength).toBeGreaterThan(1_000);
    expect(metadata).toMatchObject({ format: 'png', width: 1200, height: 630 });
  });

  it('produces byte-identical PNG output for the same input', async () => {
    const first = await renderOgImage(record);
    const second = await renderOgImage(record);

    expect(first.equals(second)).toBe(true);
  });

  it('loads bundled fonts module-relatively when the current directory changes', async () => {
    const originalDirectory = process.cwd();
    const temporaryDirectory = await mkdtemp(join(tmpdir(), 'ai-digest-og-image-'));

    try {
      process.chdir(temporaryDirectory);
      vi.resetModules();
      const { renderOgImage: renderFromMovedDirectory } = await import('./og-image');

      const png = await renderFromMovedDirectory(record);

      expect((await sharp(png).metadata()).format).toBe('png');
    } finally {
      process.chdir(originalDirectory);
      await rm(temporaryDirectory, { force: true, recursive: true });
      vi.resetModules();
    }
  }, 15_000);

  it('uses author before hostname and uppercases source type', () => {
    expect(createOgImageContent(record)).toMatchObject({ source: '王小明', sourceType: 'WEB' });
  });

  it('labels social sources in uppercase', () => {
    expect(createOgImageContent({
      ...record,
      sourceType: 'social',
      canonicalUrl: 'https://bsky.app/profile/did:plc:alice/post/3social',
    })).toMatchObject({ sourceType: 'SOCIAL' });
  });

  it('falls back to canonical hostname when author is absent', () => {
    expect(createOgImageContent({ ...record, author: null }).source).toBe('news.example.com');
  });

  it('fits text deterministically and adds one ellipsis only when truncated', () => {
    expect(fitOgText('ABCDEFGHIJK', [4, 4])).toEqual(['ABCD', 'EFG…']);
    expect(fitOgText('ABCDEFGH', [4, 4])).toEqual(['ABCD', 'EFGH']);
  });

  it('bounds title, summary, and footer source lines at the approved limits', () => {
    const layout = createOgImageLayout({
      ...record,
      title: '標'.repeat(55),
      summary: '摘'.repeat(81),
      author: '源'.repeat(37),
    });

    expect(layout.titleLines).toEqual([
      '標'.repeat(18),
      '標'.repeat(18),
      `${'標'.repeat(17)}…`,
    ]);
    expect(layout.summaryLines).toEqual(['摘'.repeat(40), `${'摘'.repeat(39)}…`]);
    expect(layout.source).toBe(`${'源'.repeat(35)}…`);
  });

  it('keeps exact title, summary, and footer boundary content without ellipses', () => {
    const layout = createOgImageLayout({
      ...record,
      title: '標'.repeat(18),
      summary: '摘'.repeat(40),
      author: '源'.repeat(36),
    });

    expect(layout.titleLines).toEqual(['標'.repeat(18)]);
    expect(layout.summaryLines).toEqual(['摘'.repeat(40)]);
    expect(layout.source).toBe('源'.repeat(36));
  });

  it('places category in the upper-right and source details across the footer', async () => {
    const png = await renderOgImage({ ...record, category: '分類位置', author: '來源位置' });

    expect(
      await countDarkGreenPixels(png, { left: 850, top: 80, width: 286, height: 60 }),
    ).toBeGreaterThan(20);
    expect(
      await countDarkGreenPixels(png, { left: 64, top: 535, width: 520, height: 55 }),
    ).toBeGreaterThan(20);
    expect(
      await countDarkGreenPixels(png, { left: 900, top: 535, width: 236, height: 55 }),
    ).toBeGreaterThan(20);
  });

  it('fails closed and reports every exact character missing from a font cmap', () => {
    const missingCharacters = new Set(['级', '战', '术', '来']);

    expect(() =>
      assertFontCoversStrings(
        {
          charToGlyphIndex(character: string) {
            return missingCharacters.has(character) ? 0 : 1;
          },
        },
        ['保姆级全攻略', '海量实战教程', '技术与未来'],
        'fixture',
      ),
    ).toThrow('OG font fixture is missing glyphs: 级, 战, 术, 来');
  });

  it('checks displayed strings against bundled font cmaps before rendering', async () => {
    vi.resetModules();
    vi.doMock('@shuding/opentype.js', () => ({
      parse: () => ({
        charToGlyphIndex(character: string) {
          return character === '级' ? 0 : 1;
        },
      }),
    }));

    try {
      const { renderOgImage: renderWithMissingGlyph } = await import('./og-image');

      await expect(
        renderWithMissingGlyph({ ...record, title: '保姆级全攻略' }),
      ).rejects.toThrow('OG font Noto Serif CJK TC Bold is missing glyphs: 级');
    } finally {
      vi.doUnmock('@shuding/opentype.js');
      vi.resetModules();
    }
  });

  it('renders title glyphs for the exact previously missing 级, 战, 术, and 来 characters', async () => {
    await expect(
      renderOgImage({ ...record, title: '保姆级全攻略：海量实战教程、技术与未来' }),
    ).resolves.toBeInstanceOf(Buffer);
  });

  it('renders summary glyphs for the exact previously missing 级, 战, 术, and 来 characters', async () => {
    await expect(
      renderOgImage({ ...record, summary: '保姆级全攻略：海量实战教程、技术与未来' }),
    ).resolves.toBeInstanceOf(Buffer);
  });

  it('keeps hostile text as inert content', () => {
    expect(createOgImageContent({ ...record, title: '<script>alert(1)</script>' }).title)
      .toBe('<script>alert(1)</script>');
  });
});
