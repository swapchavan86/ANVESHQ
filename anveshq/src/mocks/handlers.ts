import { http, HttpResponse } from 'msw';

export const handlers = [
  http.get('*/api/stocks', () => {
    return HttpResponse.json([
      {
        symbol: 'AAPL',
        name: 'Apple Inc.',
        price: 185.92,
        change: 2.45,
        changePercent: 1.34,
        riskLevel: 'Low',
        rankScore: 88,
      },
    ]);
  }),
];