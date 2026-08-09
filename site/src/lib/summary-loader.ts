import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { z } from 'zod';

import { filterAndSortSummaries, getPublishedSummaries, type SummaryRecord } from './summaries';

const nonBlankString = z.string().refine((value) => value.trim().length > 0, 'must not be blank');
const normalizedTag = nonBlankString.refine(
  (value) => value === value.trim(),
  'tag must not have surrounding whitespace',
);

const categoriesPath = resolve(process.cwd(), '..', 'data', 'categories.json');
const validCategories = new Set(
  z.array(nonBlankString).parse(JSON.parse(readFileSync(categoriesPath, 'utf8'))),
);

const tagsSchema = z
  .array(normalizedTag)
  .min(1)
  .max(5)
  .superRefine((tags, context) => {
    const normalized = tags.map((tag) => tag.toUpperCase().toLowerCase());
    if (new Set(normalized).size !== normalized.length) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: 'tags must be unique' });
    }
  });

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
  id: nonBlankString,
  canonicalUrl: z.string().url().max(2083).refine(isHttpUrl, 'canonicalUrl must use HTTP or HTTPS'),
  sourceType: z.literal('web'),
  title: nonBlankString,
  author: nonBlankString.nullable(),
  sourcePublishedAt: z.string().datetime({ offset: true }).nullable(),
  createdAt: z.string().datetime({ offset: true }),
  updatedAt: z.string().datetime({ offset: true }),
  summary: nonBlankString,
  keyPoints: z.array(nonBlankString).min(3).max(5),
  category: nonBlankString.refine((value) => validCategories.has(value), 'unknown category'),
  tags: tagsSchema,
  editorial: nonBlankString,
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
