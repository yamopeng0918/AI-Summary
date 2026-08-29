import { describe, expect, it } from 'vitest';

import { initializeSummaryImage, type SummaryImage } from './summary-image-state';

const fakeImage = (complete: boolean, naturalWidth: number) => {
  const listeners = new Map<'load' | 'error', () => void>();
  const image: SummaryImage = {
    complete,
    naturalWidth,
    dataset: {},
    addEventListener: (type, listener) => listeners.set(type, listener),
  };

  return { image, listeners };
};

describe('initializeSummaryImage', () => {
  it('keeps incomplete images pending until they load', () => {
    const { image, listeners } = fakeImage(false, 0);

    initializeSummaryImage(image);

    expect(image.dataset.imageState).toBe('pending');
    listeners.get('load')?.();
    expect(image.dataset.imageState).toBe('loaded');
  });

  it('initializes cached successful images as loaded', () => {
    const { image } = fakeImage(true, 1200);

    initializeSummaryImage(image);

    expect(image.dataset.imageState).toBe('loaded');
  });

  it('marks later image errors as failed', () => {
    const { image, listeners } = fakeImage(false, 0);

    initializeSummaryImage(image);
    listeners.get('error')?.();

    expect(image.dataset.imageState).toBe('failed');
  });

  it('initializes cached completed failures as failed', () => {
    const { image } = fakeImage(true, 0);

    initializeSummaryImage(image);

    expect(image.dataset.imageState).toBe('failed');
  });
});
