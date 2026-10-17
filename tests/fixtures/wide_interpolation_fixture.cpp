// Proposed standalone regression source only; not compiled or executed in this draft.
#include "wideInterpolationStencil.h"
#include <limits>
#include <string>
#include <type_traits>
using namespace OrbitPoc::WideInterpolation;
static void require(bool condition,const char *message)
{if(!condition)throw std::runtime_error(message);}
int main()
{
  static_assert(std::numeric_limits<long double>::digits>std::numeric_limits<double>::digits);
  const long double low=std::ldexp(1.L,-60);
  Stencil identity;identity.mode=Mode::exact;identity.indices={0};identity.weights={{1.L}};
  const long double exactValue=1.L+low;
  require(static_cast<double>(exactValue)==1.,"fixture must lose its low part in binary64");
  require(evaluate(identity,[&](std::size_t){return exactValue;})==exactValue,"exact-node low part lost");
  const long double large=std::ldexp(1.L,60);
  Stencil direct;direct.mode=Mode::ordinary;direct.indices={0,1};direct.weights={{1.L},{-1.L}};
  const long double values[2]={large+1.L,large};
  require(evaluate(direct,[&](std::size_t i){return values[i];})==1.L,"ordinary wide input rounded");
  // Deliberately non-normalized twofold pair distinguishes the ACTUAL anchor.
  // It must not be inferred from weights or replaced by an unanchored dot.
  Stencil anchored;anchored.mode=Mode::anchoredTwofold;anchored.indices={0,1};
  anchored.weights={{.5L,std::ldexp(1.L,-70)},{.5L,0.L}};
  const long double opposing[2]={large,-large};
  anchored.anchor=0;
  require(evaluate(anchored,[&](std::size_t i){return opposing[i];})==0.L,"anchor0 changed");
  anchored.anchor=1;
  require(evaluate(anchored,[&](std::size_t i){return opposing[i];})==std::ldexp(1.L,-9),"anchor1 or weight low part lost");
  {
    Capture capture(3,100);
    {
      Mapping mapping(std::array<std::size_t,2>{2,0},20);
      require(twofold(0,0,anchored.weights,1,0),"capture inactive");
      require(exact(1,7),"exact capture inactive");
    }
    {
      Mapping mapping(std::array<std::size_t,1>{1},50);
      require(exactGrid(1),"exact-grid shortcut not captured");
    }
    const auto recorded=capture.take();
    require(recorded[2].anchor==1&&recorded[2].indices==std::vector<std::size_t>({20,21}),"batch anchor/index capture changed");
    require(recorded[2].weights[0].low==std::ldexp(1.L,-70),"captured low weight lost");
    require(recorded[0].indices==std::vector<std::size_t>({27})&&recorded[1].indices==std::vector<std::size_t>({50}),"original output order lost");
  }
  bool rejected=false;
  try{Capture outer(1,10);Capture nested(1,10);}catch(const std::runtime_error&){rejected=true;}
  require(rejected,"nested capture not rejected");
  rejected=false;
  try{Capture missing(2,10);{Mapping mapping(std::array<std::size_t,1>{0},0);exact(0,0);}missing.take();}
  catch(const std::runtime_error&){rejected=true;}
  require(rejected,"missing batch output accepted");
  rejected=false;
  try{Capture repeated(1,10);Mapping mapping(std::array<std::size_t,2>{0,0},0);exact(0,0);exact(1,0);}
  catch(const std::runtime_error&){rejected=true;}
  require(rejected,"repeated batch output accepted");
  rejected=false;
  try{Capture grid(2,10);Mapping mapping(std::array<std::size_t,2>{0,1},0);exactGrid(1);}
  catch(const std::runtime_error&){rejected=true;}
  require(rejected,"wrong exact-grid metadata count accepted");
  rejected=false;anchored.anchor=2;
  try{evaluate(anchored,[&](std::size_t i){return opposing[i];});}catch(const std::runtime_error&){rejected=true;}
  require(rejected,"invalid actual anchor accepted");
}
