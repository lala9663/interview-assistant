import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import { defineConfig, globalIgnores } from 'eslint/config'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig([
  globalIgnores(['dist', 'coverage', 'public/mockServiceWorker.js']),
  {
    files: ['**/*.{ts,vue}'],
    extends: [js.configs.recommended, tseslint.configs.recommended, pluginVue.configs['flat/recommended']],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      // <script lang="ts"> inside .vue files goes through the TypeScript parser.
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // TypeScript (vue-tsc) already checks undefined names, including in .vue files.
      'no-undef': 'off',
      // shadcn-vue style primitives are single words (Button, Card, Badge).
      'vue/multi-word-component-names': 'off',
      // Optional props typed with TypeScript default to undefined (e.g. `class?: HTMLAttributes['class']`).
      'vue/require-default-prop': 'off',
      // Layout is left to the formatter; long Tailwind class lists read better on one line.
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/multiline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/html-indent': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/first-attribute-linebreak': 'off',
    },
  },
])
