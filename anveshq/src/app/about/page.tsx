export default function AboutPage() {
  return (
    <div className="bg-white py-16 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
          About ANVESHQ
        </h1>
        <p className="mt-6 text-xl text-gray-500">
          ANVESHQ is a modern market intelligence platform designed to empower
          investors and traders with data-driven insights. We believe that in
          an age of information overload, clarity and focus are the keys to
          successful market participation. Our mission is to democratize access
          to sophisticated financial tools and analytics, making institutional-grade
          research accessible to everyone.
        </p>
        <div className="mt-12">
          <h2 className="text-3xl font-bold text-gray-900">Our Vision</h2>
          <p className="mt-4 text-lg text-gray-500">
            We envision a world where every investor has the confidence to make
            informed decisions. ANVESHQ was born from the idea that financial
            markets should not be a black box. By leveraging technology and
            quantitative analysis, we aim to illuminate market trends, identify
            opportunities, and help our users navigate the complexities of the
            financial landscape with greater precision.
          </p>
        </div>
        <div className="mt-12">
          <h2 className="text-3xl font-bold text-gray-900">
            What We Do
          </h2>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="p-6 bg-gray-50 rounded-lg">
              <h3 className="text-xl font-semibold text-gray-900">
                Momentum Analysis
              </h3>
              <p className="mt-2 text-base text-gray-500">
                Our proprietary momentum algorithms scan thousands of stocks to
                identify securities with strong and persistent trends. We help you
                focus on what's moving, so you can make timely and effective
                decisions.
              </p>
            </div>
            <div className="p-6 bg-gray-50 rounded-lg">
              <h3 className="text-xl font-semibold text-gray-900">
                Data-Driven Insights
              </h3>
              <p className="mt-2 text-base text-gray-500">
                We go beyond basic market data. ANVESHQ provides deep insights
                into market dynamics, sector performance, and individual stock
                behavior, all presented in a clean, intuitive interface.
              </p>
            </div>
            <div className="p-6 bg-gray-50 rounded-lg">
              <h3 className="text-xl font-semibold text-gray-900">
                Decision Support
              </h3>
              <p className="mt-2 text-base text-gray-500">
                ANVESHQ is not just about data; it's about decision support. We
                provide the tools and context you need to build and test your
                investment theses, manage risk, and ultimately, achieve your
                financial goals.
              </p>
            </div>
            <div className="p-6 bg-gray-50 rounded-lg">
              <h3 className="text-xl font-semibold text-gray-900">
                Long-Term Vision
              </h3>
              <p className="mt-2 text-base text-gray-500">
                We are committed to continuous innovation. Our roadmap includes
                expanding our data coverage, introducing new analytical tools,
                and building a community of data-driven investors.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}