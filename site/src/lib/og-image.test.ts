import { describe, expect, it } from 'vitest';
import sharp from 'sharp';
import type { SummaryRecord } from './summaries';
import { createOgImageContent, fitOgText, renderOgImage } from './og-image';

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

describe('OG image content', () => {
  it('renders a non-empty 1200 by 630 PNG with Chinese content', async () => {
    const png = await renderOgImage(record);
    const metadata = await sharp(png).metadata();

    expect(png.byteLength).toBeGreaterThan(1_000);
    expect(metadata).toMatchObject({ format: 'png', width: 1200, height: 630 });
  });

  it('uses author before hostname and uppercases source type', () => {
    expect(createOgImageContent(record)).toMatchObject({ source: '王小明', sourceType: 'WEB' });
  });

  it('falls back to canonical hostname when author is absent', () => {
    expect(createOgImageContent({ ...record, author: null }).source).toBe('news.example.com');
  });

  it('fits text deterministically and adds one ellipsis only when truncated', () => {
    expect(fitOgText('ABCDEFGHIJK', [4, 4])).toEqual(['ABCD', 'EFG…']);
    expect(fitOgText('ABCDEFGH', [4, 4])).toEqual(['ABCD', 'EFGH']);
  });

  it('keeps hostile text as inert content', () => {
    expect(createOgImageContent({ ...record, title: '<script>alert(1)</script>' }).title)
      .toBe('<script>alert(1)</script>');
  });
});
