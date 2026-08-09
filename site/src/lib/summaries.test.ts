import { describe, expect, it } from 'vitest';

import {
  filterAndSortSummaries,
  getPublishedSummaries,
  parseSummaryRecord,
} from './summaries';

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
  category: '資料工程',
  createdAt: '2026-08-01T12:00:00+08:00',
  updatedAt: '2026-08-01T12:00:00+08:00',
} as const;

describe('summary data', () => {
  it('rejects a record with fewer than three key points', () => {
    expect(() =>
      parseSummaryRecord({ ...newerRecord, keyPoints: ['只有', '兩點'] }),
    ).toThrow();
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

    expect(filterAndSortSummaries(records, '', '資料工程', 'newest').map((record) => record.id)).toEqual([
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
});
