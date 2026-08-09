import { describe, expect, it } from 'vitest';

import { homePath, summaryPath } from './paths';

describe('Pages paths', () => {
  it('normalizes the project base to one trailing slash', () => {
    expect(homePath('/AI-Summary')).toBe('/AI-Summary/');
    expect(homePath('/AI-Summary/')).toBe('/AI-Summary/');
  });

  it('keeps root deployments valid', () => {
    expect(homePath('/')).toBe('/');
  });

  it('builds a summary path below the configured base', () => {
    expect(summaryPath('/AI-Summary/', 'demo-id')).toBe('/AI-Summary/summaries/demo-id/');
  });
});
