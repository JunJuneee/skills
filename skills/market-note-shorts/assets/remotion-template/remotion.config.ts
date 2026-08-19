import {Config} from '@remotion/cli/config';

// Use the installed Chrome on this Mac for local rendering when the bundled
// headless shell is not available.
Config.setBrowserExecutable('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
