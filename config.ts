// eslint.config.ts
import js from "@eslint/js";
import react from "eslint-plugin-react";
import tseslint from "typescript-eslint";
import globals from "globals";
import prettier from "eslint-config-prettier";

export default tseslint.config(
  // 1) Global ignores
  {
    ignores: ["node_modules", "dist", "build", ".vite", "coverage"],
  },

  // 2) Base JS rules
  js.configs.recommended,

  // 3) TypeScript rules (no type-checking mode; add type-checked preset later if needed)
  ...tseslint.configs.recommended,

  // 4) React rules
  {
    files: ["**/*.{jsx,tsx,js,ts}"],
    plugins: { react },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    settings: {
      react: { version: "detect" }, // fixes the “react version not specified” warning
    },
    rules: {
      // Add any React rules you want here, e.g.:
      "react/react-in-jsx-scope": "off", // Not needed with React 17+
    },
  },

  // 5) Turn off style rules that conflict with Prettier
  prettier
);
