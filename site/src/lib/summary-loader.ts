import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { z } from 'zod';

import { filterAndSortSummaries, getPublishedSummaries, type SummaryRecord } from './summaries';

const isHttpUrl = (value: string): boolean => {
  try {
    const { protocol } = new URL(value);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
};

export const SummaryRecordSchema: z.ZodType<SummaryRecord> = z.object({
  schemaVersion: z.literal(1),
  id: z.string(),
  canonicalUrl: z.string().url().max(2083).refine(isHttpUrl, 'canonicalUrl must use HTTP or HTTPS'),
  sourceType: z.literal('web'),
  title: z.string(),
  author: z.string().nullable(),
  sourcePublishedAt: z.string().datetime({ offset: true }).nullable(),
  createdAt: z.string().datetime({ offset: true }),
  updatedAt: z.string().datetime({ offset: true }),
  summary: z.string(),
  keyPoints: z.array(z.string()).min(3).max(5),
  category: z.string(),
  tags: z.array(z.string()).min(1).max(5),
  editorial: z.string(),
  status: z.enum(['published', 'archived']),
});

export function getSummariesDirectory(siteDirectory = process.cwd()): string {
  return resolve(siteDirectory, '..', 'data', 'summaries');
}

export function parseSummaryRecord(record: unknown): SummaryRecord {
  return SummaryRecordSchema.parse(record);
}

export function loadPublishedSummaries(): SummaryRecord[] {
  const summariesDirectory = getSummariesDirectory();
  const records = readdirSync(summariesDirectory)
    .filter((fileName) => fileName.endsWith('.json'))
    .map((fileName) => {
      const filePath = resolve(summariesDirectory, fileName);
      return parseSummaryRecord(JSON.parse(readFileSync(filePath, 'utf8')));
    });

  return filterAndSortSummaries(getPublishedSummaries(records), '', '', 'newest');
}
