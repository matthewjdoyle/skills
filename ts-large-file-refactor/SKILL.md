---
name: ts-large-file-refactor
description: Refactors large TypeScript/TSX codebases to reduce individual file sizes by systematically extracting types, constants, hard-coded content (text/images), and sub-components into organized folders. Use this skill when asked to split, organize, or modularize large TypeScript files, or when the user wants to make a website's text/image content easier to update without touching logic.
---

# ts-large-file-refactor

This skill provides expert guidance and tooling for refactoring large TypeScript/TSX files into modular, maintainable structures. The primary goals are reducing file size, organizing code by domain, and explicitly separating content (text, image URLs) from logic to empower non-developers or future developers to easily update websites.

## Workflow

### 1. Identify Target Files
If the user hasn't specified a file, use the bundled Python script to find the largest TypeScript files in the project:
```bash
python <SKILL_PATH>/scripts/find_large_files.py --dir <path-to-src> --min-lines 200
```
*(Replace `<SKILL_PATH>` with the actual path to this skill's directory, which you can determine by looking at where this `SKILL.md` is loaded from)*
This will output a list of `.ts` and `.tsx` files sorted by line count. Identify files that combine too many concerns (e.g., UI, data fetching, types, constants).

### 2. Analyze the File Structure
Use `read_file` to understand the target file. Look for natural extraction points:
- **Types/Interfaces:** Can complex type definitions be moved to `types.ts` or a `types/` directory?
- **Content/Data (Crucial):** Are there hard-coded text strings (e.g., website copy) or image URLs? **These MUST be extracted into a dedicated content file** (e.g., `content.ts` or `[ComponentName].content.ts`). This makes it extremely simple to update text/images later without modifying React components.
- **Constants:** Are there magic numbers, regexes, or config objects? Move them to `constants.ts`.
- **Helper Functions:** Pure functions should go to `utils.ts` or a `helpers/` folder.
- **Sub-components:** Break down large UI components into smaller components in separate files within a feature folder.

### 3. Propose a Plan
Before writing code, use the `enter_plan_mode` tool or simply propose a new directory structure to the user.
Example:
```text
Original:
src/components/LandingPage.tsx (800 lines)

Refactored:
src/components/LandingPage/
  ├── index.tsx (Main logic)
  ├── LandingPage.types.ts (Interfaces)
  ├── LandingPage.content.ts (Extracted text/image URLs)
  ├── LandingPage.constants.ts
  └── components/
      ├── HeroSection.tsx
      └── FeaturesSection.tsx
```

### 4. Execute the Refactoring
Apply changes iteratively:
1. **Create new files:** Use the `write_file` tool to create the new extracted files. Export the contents and ensure they use correct TypeScript typing.
2. **Update the original file:** Replace the extracted code with `import` statements. 
3. **Verify:** Check for circular dependencies and ensure all relative imports resolve correctly.
4. **Best Practices:** Do not use `any` when moving types. Do not use hard-coded strings in components—pass them as props or import them from the new `.content.ts` file.

## Why Separate Content?
By moving all user-facing copy, headers, paragraphs, and asset paths into a `.content.ts` file, you create a "single source of truth" for the site's data. A content editor can simply open `content.ts` and modify text without worrying about breaking JSX/TSX syntax or application state.
