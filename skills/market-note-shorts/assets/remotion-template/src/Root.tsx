import {Composition} from 'remotion';
import {DailyMarketCloseCalm20260814} from './DailyMarketCloseCalm20260814';

export const Root = () => (
  <Composition
    id="DailyMarketCloseCalm"
    component={DailyMarketCloseCalm20260814}
    durationInFrames={2751}
    fps={30}
    width={1080}
    height={1920}
  />
);
