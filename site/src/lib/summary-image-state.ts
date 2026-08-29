export type SummaryImageState = 'pending' | 'loaded' | 'failed';

export type SummaryImage = Pick<HTMLImageElement, 'complete' | 'naturalWidth' | 'dataset'> & {
  addEventListener(
    type: 'load' | 'error',
    listener: () => void,
    options?: AddEventListenerOptions,
  ): void;
};

const setImageState = (image: SummaryImage, state: SummaryImageState) => {
  image.dataset.imageState = state;
};

export const initializeSummaryImage = (image: SummaryImage) => {
  setImageState(image, 'pending');
  image.addEventListener('load', () => setImageState(image, 'loaded'), { once: true });
  image.addEventListener('error', () => setImageState(image, 'failed'), { once: true });
  if (image.complete) setImageState(image, image.naturalWidth > 0 ? 'loaded' : 'failed');
};
