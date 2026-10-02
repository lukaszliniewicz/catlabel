import base from './eslint.config.js';
import hooks from 'eslint-plugin-react-hooks';
export default [...base, {files:['src/**/*.{js,jsx}'], rules:hooks.configs.flat.recommended.rules}];
