import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// Check if environment variables are loaded
if (!supabaseUrl) {
  console.error('Missing VITE_SUPABASE_URL environment variable.');
  // Optionally throw an error or handle this case
  // throw new Error('Supabase URL is not defined.');
}
if (!supabaseAnonKey) {
  console.error('Missing VITE_SUPABASE_ANON_KEY environment variable.');
  // Optionally throw an error or handle this case
  // throw new Error('Supabase Anon Key is not defined.');
}

// Only create the client if both are available, otherwise it will fail anyway.
export const supabase = createClient(supabaseUrl || 'http://localhost', supabaseAnonKey || 'DUMMY_KEY');

// Log to confirm client creation (can be removed after debugging)
console.log('Supabase client initialized.');
console.log('Supabase URL:', supabaseUrl ? '******' : 'NOT SET'); // Masking sensitive URL
console.log('Supabase Anon Key:', supabaseAnonKey ? '******' : 'NOT SET'); // Masking sensitive key