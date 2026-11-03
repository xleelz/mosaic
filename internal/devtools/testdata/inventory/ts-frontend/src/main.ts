import { app } from 'electron';
enableCompileCache('main');
await import('./mainImpl.js');
