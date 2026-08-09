import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
  filterAndSortSummaries,
  getPublishedSummaries,
  reorderSummaryCards,
  serializeSummaryRecords,
} from './summaries';
import { getSummariesDirectory, parseSummaryRecord } from './summary-loader';

const approvedCategories = JSON.parse(
  readFileSync(resolve('..', 'data', 'categories.json'), 'utf8'),
) as string[];

const newerRecord = {
  schemaVersion: 1,
  id: 'newer',
  canonicalUrl: 'https://example.com/newer',
  sourceType: 'web',
  title: '生成式 AI 新聞',
  author: '編輯',
  sourcePublishedAt: '2026-08-08T10:00:00+08:00',
  createdAt: '2026-08-08T12:00:00+08:00',
  updatedAt: '2026-08-08T12:00:00+08:00',
  summary: '這是一則關於模型部署的摘要。',
  keyPoints: ['模型更小', '部署更快', '支援繁體中文'],
  category: '人工智慧',
  tags: ['模型'],
  editorial: '需持續留意評估方法。',
  status: 'published',
} as const;

const olderRecord = {
  ...newerRecord,
  id: 'older',
  canonicalUrl: 'https://example.com/older',
  title: '資料工程實務',
  summary: '整理資料管線的可維護性。',
  keyPoints: ['建立監控', '定期備份', '維護文件'],
  category: approvedCategories.find((category) => category !== newerRecord.category)!,
  createdAt: '2026-08-01T12:00:00+08:00',
  updatedAt: '2026-08-01T12:00:00+08:00',
} as const;

describe('summary data', () => {
  it('resolves the repository summary directory from the site build directory', () => {
    const siteDirectory = resolve('workspace', 'site');

    expect(getSummariesDirectory(siteDirectory)).toBe(resolve(siteDirectory, '..', 'data', 'summaries'));
  });

  it('rejects a record with fewer than three key points', () => {
    expect(() =>
      parseSummaryRecord({ ...newerRecord, keyPoints: ['只有', '兩點'] }),
    ).toThrow();
  });

  it.each([
    ['title', { title: '   ' }],
    ['key point', { keyPoints: ['   ', 'Second', 'Third'] }],
    ['tag', { tags: ['   '] }],
    ['editorial', { editorial: '   ' }],
  ])('rejects a record with a blank %s', (_field, changes) => {
    expect(() => parseSummaryRecord({ ...newerRecord, ...changes })).toThrow();
  });

  it('rejects an unknown category', () => {
    expect(() => parseSummaryRecord({ ...newerRecord, category: 'not-configured' })).toThrow();
  });

  it.each([[' AI'], ['AI '], ['AI', 'ai'], ['Straße', 'STRASSE']])(
    'rejects non-normalized or duplicate tags: %j',
    (...tags) => {
      expect(() => parseSummaryRecord({ ...newerRecord, tags })).toThrow();
    },
  );

  it.each(['javascript:alert(1)', 'data:text/html,unsafe'])('rejects a non-HTTP canonical URL: %s', (canonicalUrl) => {
    expect(() => parseSummaryRecord({ ...newerRecord, canonicalUrl })).toThrow();
  });

  it('excludes archived records', () => {
    const records = [
      parseSummaryRecord(newerRecord),
      parseSummaryRecord({ ...olderRecord, id: 'archived', status: 'archived' }),
    ];

    expect(getPublishedSummaries(records).map((record) => record.id)).toEqual(['newer']);
  });

  it('sorts newest records first', () => {
    const records = [parseSummaryRecord(olderRecord), parseSummaryRecord(newerRecord)];

    expect(filterAndSortSummaries(records, '', '', 'newest').map((record) => record.id)).toEqual([
      'newer',
      'older',
    ]);
  });

  it('sorts records oldest first when requested', () => {
    const records = [parseSummaryRecord(newerRecord), parseSummaryRecord(olderRecord)];

    expect(filterAndSortSummaries(records, '', '', 'oldest').map((record) => record.id)).toEqual([
      'older',
      'newer',
    ]);
  });

  it('filters records to one category', () => {
    const records = [parseSummaryRecord(newerRecord), parseSummaryRecord(olderRecord)];

    expect(filterAndSortSummaries(records, '', olderRecord.category, 'newest').map((record) => record.id)).toEqual([
      'older',
    ]);
  });

  it('searches titles, summaries, and key points case-insensitively', () => {
    const records = [parseSummaryRecord(newerRecord), parseSummaryRecord(olderRecord)];

    expect(filterAndSortSummaries(records, '  繁體中文  ', '', 'newest').map((record) => record.id)).toEqual([
      'newer',
    ]);
  });

  it('returns no records when the search has no match', () => {
    const records = [parseSummaryRecord(newerRecord), parseSummaryRecord(olderRecord)];

    expect(filterAndSortSummaries(records, '不存在的關鍵字', '', 'newest')).toEqual([]);
  });

  it('serializes hostile record content as valid JSON without a literal closing script tag', () => {
    const records = [parseSummaryRecord({ ...newerRecord, title: '</script><img src=x onerror=alert(1)>' })];
    const serialized = serializeSummaryRecords(records);

    expect(serialized).not.toContain('</script');
    expect(serialized).not.toContain('<');
    expect(JSON.parse(serialized)[0].title).toBe('</script><img src=x onerror=alert(1)>');
  });

  it('reorders existing cards to match the requested sort without injecting HTML', () => {
    const records = [parseSummaryRecord(newerRecord), parseSummaryRecord(olderRecord)];
    const cards = records.map((record) => ({ dataset: { summaryCard: record.id }, hidden: false }));
    const appendedIds: string[] = [];
    const container = {
      append: (...nodes: typeof cards) => appendedIds.push(...nodes.map((node) => node.dataset.summaryCard)),
    };

    reorderSummaryCards(container, cards, records, '', '', 'oldest');

    expect(appendedIds).toEqual(['older', 'newer']);
    expect(cards.every((card) => !card.hidden)).toBe(true);
  });
});
