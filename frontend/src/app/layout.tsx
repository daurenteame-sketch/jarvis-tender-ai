import type { Metadata } from 'next';
import './globals.css';
import { Providers } from './providers';
import { AppShell } from '@/components/AppShell';

export const metadata: Metadata = {
  title: 'Tender AI KZ — Тендерная Аналитика',
  description: 'Tender AI KZ — AI-система поиска прибыльных тендеров в Казахстане',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body className="bg-gray-950 text-gray-100 font-sans">
        <Providers>
          <AppShell>
            {children}
          </AppShell>
        </Providers>
      </body>
    </html>
  );
}
