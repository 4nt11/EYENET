import { redirect } from '@sveltejs/kit';

// Landing goes straight to the richest section.
export const load = () => {
  redirect(307, '/cases');
};
