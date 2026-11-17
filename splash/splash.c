/* SPDX-License-Identifier: GPL-2.0-only
 * Original Lite Dock userspace splash. Uses the existing SDL2 KMSDRM backend.
 * Deliberately independent of initramfs and of the receiver executable. */
#include <SDL.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static volatile sig_atomic_t running=1;
static void stop(int signal_number) { (void)signal_number; running=0; }
static SDL_Texture *load(SDL_Renderer *renderer,const char *directory,const char *name) {
    char path[1024];
    if(snprintf(path,sizeof(path),"%s/%s.bmp",directory,name)>=(int)sizeof(path))return NULL;
    SDL_Surface *surface=SDL_LoadBMP(path);
    if(!surface)return NULL;
    SDL_Texture *texture=SDL_CreateTextureFromSurface(renderer,surface);
    SDL_FreeSurface(surface);
    if(texture)SDL_SetTextureBlendMode(texture,SDL_BLENDMODE_BLEND);
    return texture;
}
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    signal(SIGTERM,stop); signal(SIGINT,stop);
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY,"linear");
    /* KMS can appear after the service starts. Retry locally, never hold up
     * systemd or the receiver waiting for a graphics device. */
    int ready=0;
    for(int attempt=0;attempt<100 && running;attempt++) {
        if(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_TIMER)==0){ready=1;break;}
        SDL_Quit(); usleep(100000);
    }
    if(!ready || !running)return 0;
    SDL_Window *window=SDL_CreateWindow("Lite Dock",0,0,0,0,SDL_WINDOW_FULLSCREEN_DESKTOP);
    SDL_Renderer *renderer=window?SDL_CreateRenderer(window,-1,SDL_RENDERER_ACCELERATED):NULL;
    if(!renderer){fprintf(stderr,"splash: %s\n",SDL_GetError());SDL_Quit();return 0;}
    SDL_ShowCursor(SDL_DISABLE);
    SDL_Texture *card=load(renderer,argv[1],"card"), *halo=load(renderer,argv[1],"halo"),
                *dot=load(renderer,argv[1],"dot"), *bar=load(renderer,argv[1],"bar");
    if(!card||!halo||!dot||!bar){fprintf(stderr,"splash assets: %s\n",SDL_GetError());SDL_Quit();return 0;}
    fprintf(stderr,"Lite Dock splash ready\n");
    Uint64 started=SDL_GetTicks64();
    while(running && SDL_GetTicks64()-started<60000) {
        SDL_Event event;
        while(SDL_PollEvent(&event))if(event.type==SDL_QUIT)running=0;
        int w,h;SDL_GetRendererOutputSize(renderer,&w,&h);
        float scale=fminf(w/1920.f,h/1080.f), x=w/2.f,y=h/2.f;
        float t=(SDL_GetTicks64()-started)/1000.f;
        float pulse=(sinf(t*2.25f)+1)/2;
        SDL_SetRenderDrawColor(renderer,12,14,18,255);SDL_RenderClear(renderer);
        SDL_FRect rect={x-320*scale,y-160*scale,640*scale,320*scale};
        SDL_RenderCopyF(renderer,card,NULL,&rect);
        SDL_SetTextureAlphaMod(halo,(Uint8)(90+165*pulse));
        rect=(SDL_FRect){x-32*scale,y-124*scale,64*scale,64*scale};
        SDL_RenderCopyF(renderer,halo,NULL,&rect);
        SDL_SetTextureAlphaMod(dot,(Uint8)(192+63*pulse));
        rect=(SDL_FRect){x-10*scale,y-102*scale,20*scale,20*scale};
        SDL_RenderCopyF(renderer,dot,NULL,&rect);
        rect=(SDL_FRect){x+(sinf(t*1.4f)*45-15)*scale,y+82*scale,30*scale,3*scale};
        SDL_RenderCopyF(renderer,bar,NULL,&rect);
        SDL_RenderPresent(renderer);
        SDL_Delay(33);
    }
    /* At handoff, don't restore a text VT over the retained graphic. The OS
     * closes our descriptors and the receiver takes KMS ownership next. */
    _exit(0);
}
