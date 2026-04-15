'use client';
import Link from 'next/link';
import { Search, ArrowRight } from 'lucide-react';

export default function SuppliersPage() {
  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Поставщики</h1>
        <p className="text-gray-500 text-sm mt-1">
          База поставщиков формируется автоматически в процессе анализа тендеров
        </p>
      </div>

      <div className="bg-gray-900 rounded-xl border border-gray-800 p-12">
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="w-16 h-16 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
            <Search className="w-7 h-7 text-blue-400" />
          </div>
          <div>
            <p className="text-gray-200 font-semibold text-lg">Поставщики добавляются автоматически</p>
            <p className="text-gray-500 text-sm mt-1 max-w-md">
              Для каждого прибыльного тендера Jarvis находит подходящих поставщиков из Китая, России и Казахстана.
              Откройте любой тендер чтобы увидеть найденных поставщиков.
            </p>
          </div>
          <Link
            href="/tenders?is_profitable=true"
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors mt-2"
          >
            Смотреть прибыльные тендеры
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}
