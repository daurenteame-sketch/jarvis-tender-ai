import { Suspense } from 'react';
import TendersClient from './TendersClient';

export default function TendersPage() {
  return (
    <Suspense fallback={<div className="p-8 text-gray-500">Загрузка...</div>}>
      <TendersClient />
    </Suspense>
  );
}
